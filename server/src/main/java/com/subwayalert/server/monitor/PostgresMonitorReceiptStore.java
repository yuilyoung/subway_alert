package com.subwayalert.server.monitor;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.postgresql.ds.PGSimpleDataSource;

/**
 * One dedicated session owns both the advisory lock and every receipt transaction. No reconnect.
 */
final class PostgresMonitorReceiptStore implements MonitorReceiptStore {
  private static final long LOCK_ID = 8366976688258819914L;
  private static final String TABLE = "subway_alert_private.monitor_receipts";
  private Connection connection;
  private boolean failed;

  PostgresMonitorReceiptStore(String url, String user, String password) {
    try {
      PGSimpleDataSource source = new PGSimpleDataSource();
      source.setUrl(url);
      source.setUser(user);
      source.setPassword(password);
      source.setConnectTimeout(5);
      source.setSocketTimeout(5);
      source.setLoginTimeout(5);
      source.setApplicationName("subway-alert-monitor-store");
      source.setOptions(
          "-c statement_timeout=5000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=10000");
      connection = source.getConnection();
      connection.setAutoCommit(false);
      try (PreparedStatement lock = prepare("SELECT pg_try_advisory_lock(?)")) {
        lock.setLong(1, LOCK_ID);
        try (ResultSet result = lock.executeQuery()) {
          if (!result.next() || !result.getBoolean(1))
            throw new SQLException("Monitor backend already running");
        }
      }
      try (Statement statement = connection.createStatement()) {
        statement.setQueryTimeout(5);
        statement.execute("CREATE SCHEMA IF NOT EXISTS subway_alert_private");
        statement.execute("REVOKE ALL ON SCHEMA subway_alert_private FROM PUBLIC");
        statement.execute(
            "CREATE TABLE IF NOT EXISTS "
                + TABLE
                + " ("
                + "id UUID PRIMARY KEY, session_hash VARCHAR(64) NOT NULL CHECK (session_hash ~ '^[0-9a-f]{64}$'), "
                + "fingerprint_hash VARCHAR(64) CHECK (fingerprint_hash ~ '^[0-9a-f]{64}$'), "
                + "expires_at TIMESTAMPTZ NOT NULL, "
                + "state VARCHAR(16) NOT NULL CHECK (state IN ('TRACKING','SAMPLE_MATCHED','CANCELLED','EXPIRED')), "
                + "delivery_status VARCHAR(16) NOT NULL CHECK (delivery_status IN ('NONE','SENDING','UNKNOWN','FCM_ACCEPTED','UNAVAILABLE','FAILED')))");
        statement.execute("ALTER TABLE " + TABLE + " ENABLE ROW LEVEL SECURITY");
        statement.execute("REVOKE ALL ON TABLE " + TABLE + " FROM PUBLIC");
      }
      connection.commit();
    } catch (SQLException | RuntimeException e) {
      throw poison();
    }
  }

  @Override
  public synchronized List<MonitorReceipt> restore(Instant now) {
    ensureOpen();
    try {
      try (PreparedStatement prune = prepare("DELETE FROM " + TABLE + " WHERE expires_at <= ?")) {
        prune.setTimestamp(1, Timestamp.from(now.minusSeconds(3600)));
        prune.executeUpdate();
      }
      List<MonitorReceipt> receipts = new ArrayList<>();
      try (PreparedStatement select =
              prepare(
                  "SELECT id, session_hash, fingerprint_hash, expires_at, state, delivery_status FROM "
                      + TABLE
                      + " LIMIT 501 FOR UPDATE");
          ResultSet rows = select.executeQuery()) {
        while (rows.next())
          receipts.add(
              new MonitorReceipt(
                  rows.getObject(1, UUID.class),
                  rows.getString(2),
                  rows.getString(3),
                  rows.getTimestamp(4).toInstant(),
                  rows.getString(5),
                  rows.getString(6)));
      }
      if (receipts.size() > 500) throw new SQLException("Monitor receipt capacity exceeded");
      List<MonitorReceipt> stopped = new ArrayList<>();
      try (PreparedStatement update =
          prepare("UPDATE " + TABLE + " SET state = ?, delivery_status = ? WHERE id = ?")) {
        for (MonitorReceipt receipt : receipts) {
          MonitorReceipt restored = receipt.afterRestart(now);
          stopped.add(restored);
          if (!receipt.equals(restored)) {
            update.setString(1, restored.state());
            update.setString(2, restored.deliveryStatus());
            update.setObject(3, restored.id());
            update.executeUpdate();
          }
        }
      }
      connection.commit();
      return List.copyOf(stopped);
    } catch (SQLException | RuntimeException e) {
      throw poison();
    }
  }

  @Override
  public synchronized void save(MonitorReceipt receipt) {
    ensureOpen();
    try (PreparedStatement save =
        prepare(
            "INSERT INTO "
                + TABLE
                + " (id, session_hash, fingerprint_hash, expires_at, state, delivery_status) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET session_hash = EXCLUDED.session_hash, fingerprint_hash = EXCLUDED.fingerprint_hash, expires_at = EXCLUDED.expires_at, state = EXCLUDED.state, delivery_status = EXCLUDED.delivery_status")) {
      save.setObject(1, receipt.id());
      save.setString(2, receipt.sessionHash());
      save.setString(3, receipt.fingerprintHash());
      save.setTimestamp(4, Timestamp.from(receipt.expiresAt()));
      save.setString(5, receipt.state());
      save.setString(6, receipt.deliveryStatus());
      save.executeUpdate();
      connection.commit();
    } catch (SQLException | RuntimeException e) {
      throw poison();
    }
  }

  @Override
  public synchronized void delete(UUID id) {
    ensureOpen();
    try (PreparedStatement delete = prepare("DELETE FROM " + TABLE + " WHERE id = ?")) {
      delete.setObject(1, id);
      delete.executeUpdate();
      connection.commit();
    } catch (SQLException | RuntimeException e) {
      throw poison();
    }
  }

  @Override
  public synchronized void checkAvailable() {
    ensureOpen();
    try {
      try (PreparedStatement check = prepare("SELECT 1");
          ResultSet result = check.executeQuery()) {
        if (!result.next()) throw new SQLException("Monitor storage unavailable");
      }
      connection.commit();
    } catch (SQLException | RuntimeException e) {
      throw poison();
    }
  }

  private PreparedStatement prepare(String sql) throws SQLException {
    PreparedStatement statement = connection.prepareStatement(sql);
    statement.setQueryTimeout(5);
    return statement;
  }

  private void ensureOpen() {
    if (failed || connection == null) throw new Unavailable();
  }

  private Unavailable poison() {
    failed = true;
    close();
    return new Unavailable();
  }

  @Override
  public synchronized void close() {
    failed = true;
    if (connection != null) {
      try {
        connection.close();
      } catch (SQLException ignored) {
      } finally {
        connection = null;
      }
    }
  }
}

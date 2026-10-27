package com.subwayalert.server.monitor;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Each successful operation is durable. A failure is terminal until process restart. */
public interface MonitorReceiptStore extends AutoCloseable {
  /** Atomically prune retained receipts, stop tracking and replace SENDING with UNKNOWN. */
  List<MonitorReceipt> restore(Instant now);
  void save(MonitorReceipt receipt);
  void delete(UUID id);
  void checkAvailable();
  @Override void close();

  final class Unavailable extends RuntimeException {
    public Unavailable(){super("Monitor storage unavailable");}
  }
  static MonitorReceiptStore memory(){return new MonitorReceiptStore(){
    public List<MonitorReceipt> restore(Instant now){return List.of();}
    public void save(MonitorReceipt receipt){}
    public void delete(UUID id){}
    public void checkAvailable(){}
    public void close(){}
  };}
}

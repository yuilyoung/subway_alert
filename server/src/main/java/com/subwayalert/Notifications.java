package com.subwayalert;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

/** At-least-once delivery with a durable lease and stable event ID; native client deduplicates. */
@Service
public class Notifications {
    private record Delivery(UUID id,UUID sessionId,String token,Map<String,String> payload,int attempt,Instant expires) {}
    private final JdbcTemplate db; private final TransactionTemplate tx; private final Json json;
    private final FirebaseClient firebase; private final Clock clock; private final Config config;
    public Notifications(JdbcTemplate db,TransactionTemplate tx,Json json,FirebaseClient firebase,Clock clock,Config config) {
        this.db=db;this.tx=tx;this.json=json;this.firebase=firebase;this.clock=clock;this.config=config;
    }
    private static Timestamp stamp(Instant value){return Timestamp.from(value);}
    private Delivery claim() {
        return tx.execute(unused->{
            Instant now=clock.instant();
            List<Delivery> pending=db.query("select o.*,s.fcm_token from app_private.alert_outbox o join app_private.tracking_sessions s on s.id=o.session_id where s.status='ALERT_PENDING' and o.expires_at>? and o.attempts<6 and ((o.state='PENDING' and o.next_attempt_at<=?) or (o.state='SENDING' and o.lease_until<=?)) order by o.created_at limit 1 for update of o skip locked",
                (r,n)->new Delivery(r.getObject("id",UUID.class),r.getObject("session_id",UUID.class),r.getString("fcm_token"),json.data(r.getString("payload")),r.getInt("attempts")+1,r.getTimestamp("expires_at").toInstant()),stamp(now),stamp(now),stamp(now));
            if(pending.isEmpty()) return null;
            Delivery d=pending.getFirst();
            db.update("update app_private.alert_outbox set state='SENDING',attempts=?,lease_until=? where id=?",d.attempt(),stamp(now.plusSeconds(30)),d.id());
            return d;
        });
    }
    @Scheduled(fixedDelay=2000) public void scheduledDispatch(){if(config.scheduling()) dispatch();}
    public void dispatch() {
        for(int i=0;i<10;i++) {
            Delivery d=claim(); if(d==null) return;
            Integer active=db.queryForObject("select count(*) from app_private.tracking_sessions where id=? and status='ALERT_PENDING'",Integer.class,d.sessionId());
            if(active==null||active==0) {db.update("update app_private.alert_outbox set state='CANCELLED' where id=? and state='SENDING' and attempts=?",d.id(),d.attempt());continue;}
            try {
                String result=firebase.send(d.token(),d.payload());
                tx.executeWithoutResult(unused->{
                    int written=db.update("update app_private.alert_outbox set state='SENT',sent_at=?,result_code=?,lease_until=null where id=? and state='SENDING' and attempts=?",stamp(clock.instant()),config.demo()?result:"FCM_ACCEPTED",d.id(),d.attempt());
                    if(written==1) db.update("update app_private.tracking_sessions set status='ALERTED',alerted_at=? where id=? and status='ALERT_PENDING'",stamp(clock.instant()),d.sessionId());
                });
            } catch(Exception e) {
                boolean failed=FirebaseClient.permanent(e)||d.attempt()>=6;
                boolean expired=!clock.instant().isBefore(d.expires());
                String state=expired?"EXPIRED":failed?"FAILED":"PENDING";
                tx.executeWithoutResult(unused->{
                    int written=db.update("update app_private.alert_outbox set state=?,result_code=?,next_attempt_at=?,lease_until=null where id=? and state='SENDING' and attempts=?",state,FirebaseClient.code(e),stamp(clock.instant().plusSeconds(1L<<Math.min(5,d.attempt()))),d.id(),d.attempt());
                    if(written==1&&(failed||expired)) db.update("update app_private.tracking_sessions set status=?,last_reason='DELIVERY_FAILED' where id=? and status='ALERT_PENDING'",expired?"EXPIRED":"FAILED",d.sessionId());
                });
            }
        }
    }
}

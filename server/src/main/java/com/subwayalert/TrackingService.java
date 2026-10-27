package com.subwayalert;

import com.subwayalert.core.JourneyEngine;
import com.subwayalert.core.JourneyEngine.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.*;
import java.time.*;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class TrackingService {
    record Session(UUID id,String owner,String requestHash,String line,String direction,List<String> route,String token,
                   String train,String status,int index,Instant seen,String reason,Instant created,Instant boarded,Instant expires) {}
    public record View(UUID id,String status,String lineId,String direction,List<Catalog.Station> route,String trainNo,
                       int currentIndex,int remainingStops,Instant observedAt,boolean dataFresh,String lastReason,Instant expiresAt,String mode,String alertKind) {}
    public record Candidate(String trainNo,String stationName,String terminalName,Instant observedAt) {}
    private final JdbcTemplate db; private final TransactionTemplate tx; private final Json json;
    private final Catalog catalog; private final TopisClient topis; private final Config config; private final Clock clock;
    public TrackingService(JdbcTemplate db,TransactionTemplate tx,Json json,Catalog catalog,TopisClient topis,Config config,Clock clock) {
        this.db=db;this.tx=tx;this.json=json;this.catalog=catalog;this.topis=topis;this.config=config;this.clock=clock;
    }
    private Session row(ResultSet r,int n) throws SQLException {
        return new Session(r.getObject("id",UUID.class),r.getString("owner_uid"),r.getString("request_hash"),r.getString("line_id"),r.getString("direction"),json.strings(r.getString("route")),r.getString("fcm_token"),r.getString("train_no"),r.getString("status"),r.getInt("last_index"),instant(r,"last_seen"),r.getString("last_reason"),instant(r,"created_at"),instant(r,"boarded_at"),instant(r,"expires_at"));
    }
    private static Instant instant(ResultSet r,String column) throws SQLException {Timestamp t=r.getTimestamp(column);return t==null?null:t.toInstant();}
    private static Timestamp stamp(Instant i){return i==null?null:Timestamp.from(i);}
    private Session owned(String owner,UUID id) {
        return db.query("select * from app_private.tracking_sessions where id=? and owner_uid=?",this::row,id,owner).stream().findFirst()
            .orElseThrow(()->new ResponseStatusException(HttpStatus.NOT_FOUND,"추적 세션이 없습니다."));
    }
    private static ResponseStatusException conflict(String text){return new ResponseStatusException(HttpStatus.CONFLICT,text);}
    private View view(Session s) {
        List<String> kinds=db.query("select payload->>'kind' from app_private.alert_outbox where session_id=?",(r,n)->r.getString(1),s.id());
        return new View(s.id(),s.status(),s.line(),s.direction(),s.route().stream().map(catalog::station).toList(),s.train(),s.index(),s.route().size()-1-s.index(),s.seen(),JourneyEngine.fresh(s.seen(),clock.instant()),s.reason(),s.expires(),config.demo()?"DEMO":"LIVE",kinds.isEmpty()?null:kinds.getFirst());
    }
    public View status(String owner,UUID id){expire();return view(owned(owner,id));}
    public View active(String owner) {
        expire();
        return db.query("select * from app_private.tracking_sessions where owner_uid=? and status in ('WAITING_BOARDING','TRACKING','ALERT_PENDING') order by created_at desc limit 1",this::row,owner).stream().findFirst().map(this::view).orElse(null);
    }
    public View start(String owner,Api.Start req) {
        List<String> route=catalog.route(req.lineId(),req.direction(),req.boardingStationId(),req.destinationStationId());
        if(route.size()>100) throw new IllegalArgumentException("100개 역을 초과하는 경로는 지원하지 않습니다.");
        String hash;
        try {hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest((req.lineId()+"|"+req.direction()+"|"+req.boardingStationId()+"|"+req.destinationStationId()).getBytes(StandardCharsets.UTF_8)));}
        catch(Exception e){throw new IllegalStateException(e);}
        return tx.execute(unused->{
            db.queryForObject("select pg_advisory_xact_lock(hashtext(?))",(r,n)->0,owner);
            expire();
            List<Session> old=db.query("select * from app_private.tracking_sessions where owner_uid=? and idempotency_key=?",this::row,owner,req.idempotencyKey());
            if(!old.isEmpty()) {
                if(!old.getFirst().requestHash().equals(hash)) throw conflict("동일 요청 키로 경로를 변경할 수 없습니다.");
                return view(old.getFirst());
            }
            if(active(owner)!=null) throw conflict("이미 진행 중인 추적이 있습니다. 먼저 종료하세요.");
            Integer recent=db.queryForObject("select count(*) from app_private.tracking_sessions where owner_uid=? and created_at>?",Integer.class,owner,stamp(clock.instant().minusSeconds(3600)));
            if(recent!=null&&recent>=20) throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,"잠시 후 새 추적을 시작하세요.");
            UUID id=UUID.randomUUID(); Instant now=clock.instant();
            db.update("insert into app_private.tracking_sessions(id,owner_uid,idempotency_key,request_hash,line_id,direction,route,fcm_token,status,created_at,expires_at) values (?,?,?,?,?,?,?::jsonb,?,'WAITING_BOARDING',?,?)",
                id,owner,req.idempotencyKey(),hash,req.lineId(),req.direction(),json.write(route),req.fcmToken(),stamp(now),stamp(now.plusSeconds(900)));
            return view(owned(owner,id));
        });
    }
    private List<Observation> eligible(Session s) {
        Instant now=clock.instant();
        if(config.demo()) return List.of(new Observation("DEMO-"+s.id(),s.line(),s.direction(),s.route().getFirst(),"ARRIVED",now,false,s.route().getLast()));
        return topis.positions(s.line()).stream().filter(o->o.direction().equals(s.direction())&&!o.express()
            &&JourneyEngine.fresh(o.observedAt(),now)&&o.stationId().equals(s.route().getFirst())
            &&Set.of("ENTERING","ARRIVED","DEPARTED").contains(o.state())
            &&catalog.serves(s.route(),s.line(),s.direction(),o.terminalId())).toList();
    }
    public List<Candidate> candidates(String owner,UUID id) {
        Session s=owned(owner,id);
        if(!s.status().equals("WAITING_BOARDING")) return List.of();
        return eligible(s).stream().map(o->new Candidate(o.trainNo(),catalog.station(o.stationId()).name(),catalog.station(o.terminalId()).name(),o.observedAt())).toList();
    }
    public View board(String owner,UUID id,String trainNo) {
        Session s=owned(owner,id);
        if(s.status().equals("TRACKING")&&Objects.equals(s.train(),trainNo)) return view(s);
        if(!s.status().equals("WAITING_BOARDING")||!clock.instant().isBefore(s.expires())) throw conflict("탑승 확인 대기 시간이 지났거나 세션이 종료되었습니다.");
        if(eligible(s).stream().noneMatch(o->o.trainNo().equals(trainNo))) throw new IllegalArgumentException("현재 출발역의 해당 방향 일반 열차만 선택할 수 있습니다. 목록을 새로고침하세요.");
        Instant now=clock.instant();
        int changed=db.update("update app_private.tracking_sessions set train_no=?,status='TRACKING',boarded_at=?,expires_at=?,last_reason='BOARDING_CONFIRMED' where id=? and owner_uid=? and status='WAITING_BOARDING' and expires_at>?",trainNo,stamp(now),stamp(now.plusSeconds(14400)),id,owner,stamp(now));
        if(changed!=1) throw conflict("세션 상태가 변경되었습니다.");
        return view(owned(owner,id));
    }
    public View cancel(String owner,UUID id) {
        return tx.execute(unused->{
            owned(owner,id);
            db.update("update app_private.tracking_sessions set status='CANCELLED' where id=? and status in ('WAITING_BOARDING','TRACKING','ALERT_PENDING')",id);
            db.update("update app_private.alert_outbox set state='CANCELLED' where session_id=? and state in ('PENDING','SENDING')",id);
            return view(owned(owner,id));
        });
    }
    public void token(String owner,String value) {
        db.update("update app_private.tracking_sessions set fcm_token=? where owner_uid=? and status in ('WAITING_BOARDING','TRACKING','ALERT_PENDING')",value,owner);
    }
    private void expire() {
        Instant now=clock.instant();
        db.update("update app_private.tracking_sessions set status='EXPIRED',last_reason='SESSION_EXPIRED' where expires_at<=? and status in ('WAITING_BOARDING','TRACKING','ALERT_PENDING')",stamp(now));
        db.update("update app_private.alert_outbox o set state='EXPIRED' where o.state in ('PENDING','SENDING') and (o.expires_at<=? or exists(select 1 from app_private.tracking_sessions s where s.id=o.session_id and s.status='EXPIRED'))",stamp(now));
        db.update("update app_private.tracking_sessions s set status='EXPIRED',last_reason='ALERT_DELIVERY_EXPIRED' where s.status='ALERT_PENDING' and exists(select 1 from app_private.alert_outbox o where o.session_id=s.id and o.state='EXPIRED')");
    }
    @Scheduled(fixedDelay=10000) public void scheduledPoll(){if(config.scheduling()) poll();}
    public void poll() {
        expire();
        List<Session> sessions=db.query("select * from app_private.tracking_sessions where status='TRACKING' order by line_id",this::row);
        Map<String,List<Observation>> byLine=new HashMap<>();
        for(Session s:sessions) {
            if(byLine.containsKey(s.line())) continue;
            try {
                if(config.demo()) {
                    byLine.put(s.line(),sessions.stream().filter(t->t.line().equals(s.line())).map(t->{
                        int index=(int)Math.min(t.route().size()-1,Math.max(0,Duration.between(t.boarded(),clock.instant()).getSeconds()/10));
                        return new Observation(t.train(),t.line(),t.direction(),t.route().get(index),"DEPARTED",clock.instant(),false,t.route().getLast());
                    }).toList());
                } else byLine.put(s.line(),topis.positions(s.line()));
            } catch(RuntimeException e) {
                byLine.put(s.line(),List.of());
                db.update("update app_private.tracking_sessions set last_reason='UPSTREAM_UNAVAILABLE' where line_id=? and status='TRACKING'",s.line());
            }
        }
        for(Session s:sessions) {
            List<Observation> positions=byLine.getOrDefault(s.line(),List.of()).stream().filter(o->o.trainNo().equals(s.train())&&o.direction().equals(s.direction())).sorted(Comparator.comparing(Observation::observedAt)).toList();
            for(Observation o:positions) apply(s.id(),o);
        }
    }
    private void apply(UUID id,Observation o) {
        tx.executeWithoutResult(unused->{
            List<Session> rows=db.query("select * from app_private.tracking_sessions where id=? and status='TRACKING' for update",this::row,id);
            if(rows.isEmpty()) return; Session s=rows.getFirst(); Instant now=clock.instant();
            Decision d=JourneyEngine.evaluate(new Journey(s.train(),s.line(),s.direction(),s.route(),s.index(),s.seen(),false,s.expires()),o,now);
            if(d.action().equals("IGNORE")) {db.update("update app_private.tracking_sessions set last_reason=? where id=?",d.reason(),id);return;}
            if(d.action().equals("EXPIRED")){db.update("update app_private.tracking_sessions set status='EXPIRED' where id=?",id);return;}
            db.update("update app_private.tracking_sessions set last_index=?,last_seen=?,last_reason=? where id=?",d.index(),stamp(d.observedAt()),d.reason(),id);
            if(!Set.of("ALERT","LATE").contains(d.action())) return;
            UUID event=UUID.nameUUIDFromBytes(("exit:"+id).getBytes(StandardCharsets.UTF_8));
            String destination=catalog.station(s.route().getLast()).name();
            Map<String,String> payload=Map.of("eventId",event.toString(),"sessionId",id.toString(),"kind",d.action(),"destination",destination,
                "title",d.action().equals("LATE")?"목적지 도착 정보 확인":"한 정거장 전 · 하차 준비",
                "body",d.action().equals("LATE")?destination+" 도착이 확인됐습니다. 데이터 지연 가능성이 있으니 차내 안내를 확인하세요.":"다음 역은 "+destination+"입니다. 내릴 준비를 해주세요.",
                "expiresAt",Long.toString(now.plusSeconds(90).toEpochMilli()));
            db.update("insert into app_private.alert_outbox(id,session_id,payload,state,next_attempt_at,expires_at,created_at) values (?,?,?::jsonb,'PENDING',?,?,?) on conflict(session_id) do nothing",event,id,json.write(payload),stamp(now),stamp(now.plusSeconds(90)),stamp(now));
            db.update("update app_private.tracking_sessions set status='ALERT_PENDING' where id=?",id);
        });
    }
    @Scheduled(fixedDelay=3600000) public void retention() {
        if(config.scheduling()) db.update("delete from app_private.tracking_sessions where created_at<? and status not in ('WAITING_BOARDING','TRACKING','ALERT_PENDING')",stamp(clock.instant().minus(Duration.ofDays(7))));
    }
}

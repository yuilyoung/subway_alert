package com.subwayalert;

import com.subwayalert.core.JourneyEngine;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class Catalog {
    public record Direction(String code,String label) {}
    public record Line(String id,String name,String topisName,List<Direction> directions) {}
    public record Station(String id,String lineId,String name,String topisId,Double latitude,Double longitude,String source,String sourceUrl) {}
    public record Facility(String kind,String title,String location,String gateSide,String direction,String transferLine,String carDoor,String sourceUrl,Instant verifiedAt) {}
    private final JdbcTemplate db;
    private final Config config;
    public Catalog(JdbcTemplate db,Config config) { this.db=db; this.config=config; }
    public List<Line> lines() {
        return db.query("select * from app_private.lines where demo=? order by id",(rs,n)->new Line(rs.getString("id"),rs.getString("name"),rs.getString("topis_name"),
            List.of(new Direction("0",rs.getString("up_label")),new Direction("1",rs.getString("down_label")))),config.demo());
    }
    public Line line(String id) {
        return lines().stream().filter(l->l.id().equals(id)).findFirst().orElseThrow(()->new IllegalArgumentException("지원하지 않는 호선입니다."));
    }
    public List<Station> stations(String query,String lineId) {
        String q=query==null?"":query.strip();
        if(q.length()>80) throw new IllegalArgumentException("검색어는 80자 이내로 입력하세요.");
        return db.query("select s.* from app_private.subway_stations s join app_private.lines l on l.id=s.line_id where l.demo=? and (?='' or s.line_id=?) and position(lower(?) in lower(s.name))>0 order by s.name,s.id limit 100",
            (rs,n)->new Station(rs.getString("id"),rs.getString("line_id"),rs.getString("name"),rs.getString("topis_id"),rs.getObject("latitude",Double.class),rs.getObject("longitude",Double.class),rs.getString("source"),rs.getString("source_url")),config.demo(),lineId==null?"":lineId,lineId==null?"":lineId,q);
    }
    public List<Station> nearby(double latitude,double longitude) {
        if(!Double.isFinite(latitude)||!Double.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180)
            throw new IllegalArgumentException("위도·경도를 확인하세요.");
        return db.query("select * from (select s.*,6371000*2*asin(sqrt(least(1,power(sin(radians(s.latitude-?)/2),2)+cos(radians(?))*cos(radians(s.latitude))*power(sin(radians(s.longitude-?)/2),2)))) as distance from app_private.subway_stations s join app_private.lines l on l.id=s.line_id where l.demo=? and s.latitude is not null) nearby where distance<=1000 order by distance limit 10",
            (rs,n)->new Station(rs.getString("id"),rs.getString("line_id"),rs.getString("name"),rs.getString("topis_id"),rs.getObject("latitude",Double.class),rs.getObject("longitude",Double.class),rs.getString("source"),rs.getString("source_url")),latitude,latitude,longitude,config.demo());
    }
    public Station station(String id) {
        List<Station> found=db.query("select s.* from app_private.subway_stations s join app_private.lines l on l.id=s.line_id where s.id=? and l.demo=?",
            (rs,n)->new Station(rs.getString("id"),rs.getString("line_id"),rs.getString("name"),rs.getString("topis_id"),rs.getObject("latitude",Double.class),rs.getObject("longitude",Double.class),rs.getString("source"),rs.getString("source_url")),id,config.demo());
        if(found.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"역 정보가 없습니다.");
        return found.getFirst();
    }
    public Optional<String> fromTopis(String line,String topisId) {
        return db.query("select s.id from app_private.subway_stations s join app_private.lines l on l.id=s.line_id where s.line_id=? and s.topis_id=? and l.demo=?",(rs,n)->rs.getString(1),line,topisId,config.demo()).stream().findFirst();
    }
    public List<Facility> facilities(String stationId) {
        station(stationId);
        return db.query("select * from app_private.station_facilities where station_id=? order by kind,title",(rs,n)->new Facility(rs.getString("kind"),rs.getString("title"),rs.getString("location"),rs.getString("gate_side"),rs.getString("direction"),rs.getString("transfer_line"),rs.getString("car_door"),rs.getString("source_url"),rs.getTimestamp("verified_at").toInstant()),stationId);
    }
    public List<String> route(String line,String direction,String from,String to) {
        line(line);
        if(!station(from).lineId().equals(line)||!station(to).lineId().equals(line)) throw new IllegalArgumentException("동일 호선의 역을 선택하세요.");
        List<JourneyEngine.Edge> edges=db.query("select * from app_private.station_edges where line_id=? and direction=? order by from_id,to_id",
            (rs,n)->new JourneyEngine.Edge(rs.getString("from_id"),rs.getString("to_id"),rs.getString("line_id"),rs.getString("direction")),line,direction);
        return JourneyEngine.path(edges,line,direction,from,to);
    }
    public boolean serves(List<String> route,String line,String direction,String terminal) {
        if(terminal==null||terminal.isBlank()) return false;
        String origin=route.getFirst(), destination=route.getLast();
        if(terminal.equals(destination)) return true;
        try {
            // Terminal beyond destination is valid only when its directed route contains our exact prefix.
            List<String> toTerminal=route(line,direction,origin,terminal);
            return toTerminal.size()>=route.size() && toTerminal.subList(0,route.size()).equals(route);
        } catch(IllegalArgumentException e) {
            if(!terminal.equals(origin)) return false;
            // Circular service ending at the boarding station after a full circuit.
            try { return route(line,direction,destination,terminal).size()>1; } catch(IllegalArgumentException ignored) { return false; }
        }
    }
}

package com.subwayalert;

import java.time.Instant;
import java.sql.Timestamp;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class DemoData implements ApplicationRunner {
    private final JdbcTemplate db; private final Config config;
    public DemoData(JdbcTemplate db,Config config){this.db=db;this.config=config;}
    @Override @Transactional public void run(ApplicationArguments args) {
        if(!config.demo()) return;
        db.update("insert into app_private.lines values ('DEMO','데모선','DEMO','데모 도착역 방면','데모 출발역 방면',true) on conflict do nothing");
        String[] names={"데모 출발역","데모 중앙역","데모 공원역","데모 도착역","데모 종착역"};
        for(int i=0;i<names.length;i++) {
            String id="demo-"+(char)('a'+i);
            db.update("insert into app_private.subway_stations(id,line_id,topis_id,name,source,source_url,verified_at) values (?,?,?,?,?,?,?) on conflict do nothing",id,"DEMO",id,names[i],"SYNTHETIC_DEMO","urn:subway-alert:synthetic-demo",Timestamp.from(Instant.parse("2026-10-27T00:00:00Z")));
            if(i>0) {
                String before="demo-"+(char)('a'+i-1);
                db.update("insert into app_private.station_edges values ('DEMO','0',?,?) on conflict do nothing",before,id);
                db.update("insert into app_private.station_edges values ('DEMO','1',?,?) on conflict do nothing",id,before);
            }
        }
    }
}

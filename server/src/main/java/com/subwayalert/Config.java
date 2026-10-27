package com.subwayalert;

import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class Config {
    private final Environment env;
    public Config(Environment env) { this.env=env; }
    public boolean demo() { return env.getProperty("app.demo",Boolean.class,false); }
    public boolean scheduling() { return env.getProperty("app.scheduling",Boolean.class,true); }
    public String get(String name) { return env.getProperty(name,""); }
    public int budget() { return env.getProperty("app.topis-daily-budget",Integer.class,9000); }
}

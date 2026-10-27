package com.subwayalert;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class AuthFilter extends OncePerRequestFilter {
    private final Config config; private final FirebaseClient firebase;
    public AuthFilter(Config config,FirebaseClient firebase){this.config=config;this.firebase=firebase;}
    @Override protected boolean shouldNotFilter(HttpServletRequest req){return !req.getRequestURI().startsWith("/api/track");}
    @Override protected void doFilterInternal(HttpServletRequest req,HttpServletResponse res,FilterChain chain) throws ServletException,IOException {
        String uid;
        try {
            if(config.demo()) {
                uid=req.getHeader("X-Demo-User");
                if(uid==null||!uid.matches("[A-Za-z0-9_-]{1,100}")) throw new IllegalArgumentException();
                uid="demo:"+uid;
            } else {
                String auth=req.getHeader("Authorization");
                if(auth==null||!auth.startsWith("Bearer ")||auth.length()>8192) throw new IllegalArgumentException();
                uid=firebase.verify(auth.substring(7));
            }
        } catch(Exception e) {
            res.setStatus(401);res.setContentType("application/json;charset=UTF-8");
            res.getWriter().write("{\"error\":\"인증이 필요합니다. 앱을 다시 열어 주세요.\"}");return;
        }
        req.setAttribute("uid",uid); chain.doFilter(req,res);
    }
}

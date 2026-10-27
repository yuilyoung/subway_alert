package com.subwayalert.server.access;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.function.LongSupplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** Private development-device API gate. Session capability checks remain in the controllers. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public final class ApiAccessFilter extends OncePerRequestFilter {
  private final List<byte[]> tokenHashes;
  private final ApiRateLimits limits;

  @Autowired
  public ApiAccessFilter(@Value("${SUBWAY_API_TOKENS:}") String configuredTokens) {
    this(configuredTokens,System::nanoTime,Clock.systemUTC());
  }

  public ApiAccessFilter(String configuredTokens,LongSupplier elapsedNanos,Clock clock) {
    tokenHashes=parseTokens(configuredTokens);
    limits=new ApiRateLimits(tokenHashes.size(),elapsedNanos,clock);
  }

  @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)
      throws ServletException,IOException {
    if("GET".equals(request.getMethod()) && "/api/health".equals(request.getRequestURI())) {
      chain.doFilter(request,response); return;
    }
    if(tokenHashes.isEmpty()) { reject(response,503,"API_UNAVAILABLE"); return; }
    long retry=limits.preAuthentication();
    if(retry>0) { rateLimited(response,retry);return; }
    List<String> headers=Collections.list(request.getHeaders("Authorization"));
    if(headers.size()!=1 || !headers.get(0).matches("(?i:Bearer) [A-Za-z0-9_-]{32,128}")) {
      reject(response,401,"API_UNAUTHORIZED"); return;
    }
    byte[] provided=digest(headers.get(0).substring(7));
    int key=-1;
    for(int i=0;i<tokenHashes.size();i++)
      if(MessageDigest.isEqual(tokenHashes.get(i),provided))key=i;
    if(key<0) { reject(response,401,"API_UNAUTHORIZED"); return; }
    // MVC routes are relative to the container and servlet mapping, never forwarded headers.
    String route=request.getPathInfo();
    if(route==null)route=request.getRequestURI().substring(request.getContextPath().length());
    retry=limits.authenticated(key,request.getMethod(),route);
    if(retry>0) { rateLimited(response,retry);return; }
    if(!canonicalPath(request.getRequestURI())) { reject(response,400,"API_INVALID_PATH");return; }
    chain.doFilter(request,response);
  }

  private static boolean canonicalPath(String path) {
    if(path.contains("%") || path.contains(";") || path.contains("\\") || path.contains("//"))return false;
    for(String segment:path.split("/",-1))if(segment.equals(".") || segment.equals(".."))return false;
    return true;
  }
  private static void rateLimited(HttpServletResponse response,long retry) throws IOException {
    response.setHeader("Retry-After",Long.toString(retry));
    reject(response,429,"API_RATE_LIMITED");
  }

  private static List<byte[]> parseTokens(String configured) {
    if(configured==null || configured.isBlank()) return List.of();
    String[] tokens=configured.split(",",-1);
    if(tokens.length>20) throw invalidConfiguration();
    List<byte[]> hashes=new ArrayList<>();
    for(String token:tokens) {
      if(!token.matches("[A-Za-z0-9_-]{32,128}")) throw invalidConfiguration();
      hashes.add(digest(token));
    }
    return List.copyOf(hashes);
  }
  private static IllegalArgumentException invalidConfiguration() {
    return new IllegalArgumentException("Invalid private API token configuration");
  }
  private static byte[] digest(String token) {
    try { return MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.US_ASCII)); }
    catch(NoSuchAlgorithmException e) { throw new IllegalStateException("SHA-256 unavailable",e); }
  }
  private static void reject(HttpServletResponse response,int status,String code) throws IOException {
    response.setStatus(status);
    response.setContentType("application/json");
    response.setCharacterEncoding(StandardCharsets.UTF_8.name());
    response.getWriter().write("{\"error\":\""+code+"\"}");
  }
}

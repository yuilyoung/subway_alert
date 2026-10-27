package com.subwayalert.server.push;

/** Acceptance means the provider accepted the request, not that a phone displayed it. */
public interface NotificationGateway {
  enum Result { ACCEPTED, UNAVAILABLE, FAILED }
  boolean available();
  Result send(String token, String previousStation, String destinationStation, String mode);
}

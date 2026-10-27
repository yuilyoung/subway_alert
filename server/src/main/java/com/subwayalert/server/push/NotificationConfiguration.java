package com.subwayalert.server.push;

import com.google.auth.oauth2.GoogleCredentials;
import com.google.firebase.FirebaseApp;
import com.google.firebase.FirebaseOptions;
import com.google.firebase.messaging.FirebaseMessaging;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class NotificationConfiguration {
  /** Credentials are always loaded from ADC on the server, never from requests or the app. */
  @Bean
  public NotificationGateway notificationGateway() {
    String enabled = System.getenv("FCM_ENABLED");
    String projectId = System.getenv("FIREBASE_PROJECT_ID");
    if (!"true".equalsIgnoreCase(enabled) || projectId == null || projectId.isBlank()) {
      return FirebaseNotificationGateway.disabled();
    }
    try {
      FirebaseOptions options = options(GoogleCredentials.getApplicationDefault(), projectId);
      FirebaseApp app = FirebaseApp.initializeApp(options, "subway-alert-fcm");
      return FirebaseNotificationGateway.using(FirebaseMessaging.getInstance(app));
    } catch (Exception e) {
      // Missing credentials or configuration should fail closed without emitting secrets.
      return FirebaseNotificationGateway.disabled();
    }
  }

  static FirebaseOptions options(GoogleCredentials credentials, String projectId) {
    return FirebaseOptions.builder().setCredentials(credentials).setProjectId(projectId.strip())
        .setConnectTimeout(5000).setReadTimeout(5000).setWriteTimeout(5000).build();
  }
}

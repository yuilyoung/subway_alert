package com.subwayalert;

import com.google.auth.oauth2.GoogleCredentials;
import com.google.firebase.FirebaseApp;
import com.google.firebase.FirebaseOptions;
import com.google.firebase.auth.FirebaseAuth;
import com.google.firebase.messaging.*;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class FirebaseClient {
    private final FirebaseApp app;
    public FirebaseClient(Config config) throws Exception {
        if(config.demo()) { app=null; return; }
        String project=config.get("app.firebase-project-id");
        if(project.isBlank()||config.get("app.topis-key").isBlank())
            throw new IllegalStateException("Live mode requires FIREBASE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS and TOPIS_API_KEY.");
        app=FirebaseApp.initializeApp(FirebaseOptions.builder().setProjectId(project)
            .setCredentials(GoogleCredentials.getApplicationDefault()).build(),"subway-alert");
    }
    public String verify(String token) throws Exception {
        if(app==null) throw new IllegalStateException("Live auth is not configured");
        return FirebaseAuth.getInstance(app).verifyIdToken(token).getUid();
    }
    public String send(String token,Map<String,String> data) throws Exception {
        if(app==null) return "DEMO_ACCEPTED_NOT_DELIVERED";
        Message message=Message.builder().setToken(token).putAllData(data)
            .setAndroidConfig(AndroidConfig.builder().setPriority(AndroidConfig.Priority.HIGH)
                .setTtl(90_000L).setCollapseKey(data.get("eventId")).build()).build();
        return FirebaseMessaging.getInstance(app).send(message);
    }
    public static boolean permanent(Exception e) {
        if(!(e instanceof FirebaseMessagingException f)) return false;
        MessagingErrorCode c=f.getMessagingErrorCode();
        return c==MessagingErrorCode.UNREGISTERED||c==MessagingErrorCode.INVALID_ARGUMENT||c==MessagingErrorCode.SENDER_ID_MISMATCH;
    }
    public static String code(Exception e) {
        if(e instanceof FirebaseMessagingException f && f.getMessagingErrorCode()!=null) return f.getMessagingErrorCode().name();
        return "DELIVERY_ERROR"; // Never log tokens, credentials or provider URLs containing keys.
    }
}

package com.subwayalert

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.tasks.Tasks
import com.google.firebase.FirebaseApp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.messaging.FirebaseMessaging
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit
import org.json.JSONObject

object NativeAccess {
    fun configured(context: Context) = FirebaseApp.getApps(context).isNotEmpty()
    fun fine(context: Context) = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    fun background(context: Context) = Build.VERSION.SDK_INT < 29 || ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED
    fun notifications(context: Context) = NotificationManagerCompat.from(context).areNotificationsEnabled()
    fun capabilities(context: Context): JSONObject = JSONObject().put("fineLocation", fine(context))
        .put("backgroundLocation", background(context)).put("notifications", notifications(context)).put("firebaseConfigured", configured(context))
    fun identity(context: Context): JSONObject {
        val state = StateStore.state(context)
        if (state.getBoolean("demo")) return JSONObject().put("uid", state.getString("installId")).put("idToken", "").put("fcmToken", "DEMO")
        check(configured(context)) { "Firebase 설정 파일과 익명 로그인 설정이 필요합니다." }
        val auth = FirebaseAuth.getInstance()
        val user = auth.currentUser ?: Tasks.await(auth.signInAnonymously(), 20, TimeUnit.SECONDS).user
            ?: error("익명 로그인에 실패했습니다.")
        val token = Tasks.await(user.getIdToken(false), 20, TimeUnit.SECONDS).token ?: error("인증 토큰이 없습니다.")
        val fcm = Tasks.await(FirebaseMessaging.getInstance().token, 20, TimeUnit.SECONDS)
        return JSONObject().put("uid", user.uid).put("idToken", token).put("fcmToken", fcm)
    }
    class ApiFailure(val code: Int) : Exception("서버 요청 실패 ($code)")
    fun request(context: Context, identity: JSONObject, method: String, path: String, body: JSONObject? = null): JSONObject {
        val state = StateStore.state(context)
        val connection = URL(state.getString("baseUrl") + path).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 10_000
            connection.readTimeout = 15_000
            connection.instanceFollowRedirects = false // Never forward credentials to a redirect destination.
            connection.requestMethod = method
            connection.setRequestProperty("Accept", "application/json")
            if (state.getBoolean("demo")) connection.setRequestProperty("X-Demo-User", identity.getString("uid"))
            else connection.setRequestProperty("Authorization", "Bearer ${identity.getString("idToken")}")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=UTF-8")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            if (code !in 200..299) throw ApiFailure(code)
            val bytes = ByteArrayOutputStream()
            connection.inputStream.use { input ->
                val buffer = ByteArray(4096)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    check(bytes.size() + count <= 1_048_576) { "응답이 너무 큽니다." }
                    bytes.write(buffer, 0, count)
                }
            }
            val text = bytes.toString("UTF-8")
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally { connection.disconnect() }
    }
}

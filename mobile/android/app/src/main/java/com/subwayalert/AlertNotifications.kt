package com.subwayalert

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray

object AlertNotifications {
    private const val ARRIVAL = "subway-arrival-v1"
    private const val COMMUTE = "subway-commute-v1"
    fun channels(context: Context) {
        if (Build.VERSION.SDK_INT >= 26) {
            val manager = context.getSystemService(NotificationManager::class.java)
            val arrival = NotificationChannel(ARRIVAL, "하차 한 정거장 전", NotificationManager.IMPORTANCE_HIGH)
            arrival.description = "선택한 열차의 목적지 직전역 출발 알림"
            arrival.enableVibration(true)
            arrival.vibrationPattern = longArrayOf(0, 600, 200, 600, 200, 600)
            arrival.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION), AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION).build())
            manager.createNotificationChannel(arrival)
            manager.createNotificationChannel(NotificationChannel(COMMUTE, "출퇴근 탑승 확인", NotificationManager.IMPORTANCE_DEFAULT))
        }
    }
    private fun open(context: Context, id: String): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).setData(Uri.parse("subwayalert://session/$id"))
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    @Synchronized fun arrival(context: Context, data: Map<String, String>) {
        val session = data["sessionId"] ?: return
        val event = data["eventId"] ?: return
        val expires = data["expiresAt"]?.toLongOrNull() ?: return
        if (data["kind"] !in listOf("ALERT", "LATE") || expires <= System.currentTimeMillis()) return
        if (StateStore.prefs(context).getString("sessionId", "") != session) return
        val previous = JSONArray(StateStore.prefs(context).getString("seenEvents", "[]"))
        if ((0 until previous.length()).any { previous.getString(it) == event }) return
        if (!NativeAccess.notifications(context)) return
        show(context, ARRIVAL, session, data["title"] ?: "하차 알림", data["body"] ?: "차내 안내를 확인하세요.", true)
        val next = JSONArray()
        for (i in maxOf(0, previous.length() - 49) until previous.length()) next.put(previous.getString(i))
        next.put(event)
        StateStore.prefs(context).edit().putString("seenEvents", next.toString()).apply()
    }
    fun commute(context: Context, session: String, label: String) = show(context, COMMUTE, session,
        "$label · 탑승 확인", "출발역 접근을 감지했습니다. 탑승한 열차를 선택하면 하차 알림을 시작합니다.", false)
    fun ambiguous(context: Context) = show(context, COMMUTE, "ambiguous", "출퇴근 경로를 선택하세요",
        "현재 시간과 위치에 맞는 즐겨찾기가 여러 개입니다. 자동으로 목적지를 추측하지 않습니다.", false)
    fun demo(context: Context) = show(context, ARRIVAL, "demo", "[테스트] 하차 알림",
        "백그라운드 알림 표시 테스트입니다. 실제 열차 정보가 아닙니다.", true)
    private fun show(context: Context, channel: String, id: String, title: String, body: String, urgent: Boolean) {
        if (!NativeAccess.notifications(context)) return
        channels(context)
        val notification = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_notification).setContentTitle(title).setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body)).setContentIntent(open(context, id))
            .setAutoCancel(true).setOnlyAlertOnce(true).setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPriority(if (urgent) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setVibrate(if (urgent) longArrayOf(0, 600, 200, 600) else longArrayOf(0, 250))
            .setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION))
            .setTimeoutAfter(if (urgent) 120_000L else 900_000L).build()
        NotificationManagerCompat.from(context).notify(id, 100, notification)
    }
    fun clear(context: Context, session: String) { NotificationManagerCompat.from(context).cancel(session, 100) }
}

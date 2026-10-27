package com.subwayalert

import android.content.Context
import android.location.Location
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.google.android.gms.tasks.Tasks
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit
import org.json.JSONObject

class CommuteWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val context = applicationContext
        try {
            val action = inputData.getString("action") ?: "scan"
            if (action == "demo") { AlertNotifications.demo(context); return Result.success() }
            if (action == "restore") { Geofences.sync(context); return Result.success() }
            val state = StateStore.state(context)
            if (state.getBoolean("demo")) return Result.success()
            if (action == "token") {
                val identity = NativeAccess.identity(context)
                NativeAccess.request(context, identity, "PUT", "/api/track/device-token", JSONObject().put("fcmToken", identity.getString("fcmToken")))
                return Result.success()
            }
            if (!NativeAccess.fine(context) || !NativeAccess.background(context) || !NativeAccess.notifications(context)) {
                StateStore.error(context, "자동 시작에 필요한 위치 또는 알림 권한이 해제됐습니다."); return Result.failure()
            }
            val now = ZonedDateTime.now(ZoneId.of("Asia/Seoul"))
            val eligible = StateStore.favorites(context).mapNotNull { f ->
                if (!f.getBoolean("enabled")) null else {
                    val day = CommuteWindow.serviceDate(StateStore.days(f), f.getString("start"), f.getString("end"), now,
                        StateStore.prefs(context).getString("fired:${f.getString("id")}", null))
                    if (day == null) null else f to day
                }
            }
            if (eligible.isEmpty()) return Result.success()
            val fix = location() ?: return Result.success()
            val age = System.currentTimeMillis() - fix.time
            if (age !in 0..300_000 || fix.accuracy > 150) return Result.success()
            val nearby = eligible.filter { (f, _) ->
                val origin = f.getJSONObject("origin")
                val distance = FloatArray(1)
                Location.distanceBetween(fix.latitude, fix.longitude, origin.getDouble("latitude"), origin.getDouble("longitude"), distance)
                distance[0] <= 300f
            }
            if (nearby.isEmpty()) return Result.success()
            if (nearby.size > 1) { AlertNotifications.ambiguous(context); return Result.success() }
            val (favorite, day) = nearby.first()
            val identity = NativeAccess.identity(context)
            val active = NativeAccess.request(context, identity, "GET", "/api/track/active").optJSONObject("session")
            if (active != null) { StateStore.setSession(context, active.getString("id")); return Result.success() }
            val body = JSONObject().put("lineId", favorite.getJSONObject("origin").getString("lineId"))
                .put("direction", favorite.getString("direction"))
                .put("boardingStationId", favorite.getJSONObject("origin").getString("id"))
                .put("destinationStationId", favorite.getJSONObject("destination").getString("id"))
                .put("fcmToken", identity.getString("fcmToken"))
                .put("idempotencyKey", "commute:${favorite.getString("id")}:$day")
            val session = NativeAccess.request(context, identity, "POST", "/api/track", body)
            check(StateStore.prefs(context).edit().putString("fired:${favorite.getString("id")}", day).commit())
            if (session.getString("status") == "WAITING_BOARDING") {
                StateStore.setSession(context, session.getString("id"))
                AlertNotifications.commute(context, session.getString("id"), favorite.getString("label"))
            }
            StateStore.error(context, "")
            return Result.success()
        } catch (e: NativeAccess.ApiFailure) {
            if (e.code == 409) return Result.success() // Another manual or automatic session won the server-side race.
            StateStore.error(context, "출퇴근 자동 시작 서버 연결 실패 (${e.code})")
            return if ((e.code >= 500 || e.code == 429) && runAttemptCount < 3) Result.retry() else Result.failure()
        } catch (e: Exception) {
            StateStore.error(context, "자동 시작을 완료하지 못했습니다. 앱에서 권한과 서버 연결을 확인하세요.")
            return if (runAttemptCount < 3) Result.retry() else Result.failure()
        }
    }
    private fun location(): Location? {
        val timestamp = inputData.getLong("time", 0)
        if (timestamp > 0 && System.currentTimeMillis() - timestamp in 0..300_000) {
            return Location("geofence").apply {
                latitude = inputData.getDouble("latitude", Double.NaN)
                longitude = inputData.getDouble("longitude", Double.NaN)
                accuracy = inputData.getDouble("accuracy", 9999.0).toFloat()
                time = timestamp
            }
        }
        val source = CancellationTokenSource()
        return try {
            Tasks.await(LocationServices.getFusedLocationProviderClient(applicationContext)
                .getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, source.token), 12, TimeUnit.SECONDS)
        } finally { source.cancel() }
    }
}

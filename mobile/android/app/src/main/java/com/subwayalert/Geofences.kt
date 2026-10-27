package com.subwayalert

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.work.*
import com.google.android.gms.location.*
import com.google.android.gms.tasks.Tasks
import java.util.concurrent.TimeUnit

object Geofences {
    private fun pending(context: Context): PendingIntent {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
        return PendingIntent.getBroadcast(context, 101, Intent(context, GeofenceReceiver::class.java), flags)
    }
    @Synchronized fun sync(context: Context) {
        val enabled = StateStore.favorites(context).filter { it.getBoolean("enabled") }
        val client = LocationServices.getGeofencingClient(context)
        if (enabled.isEmpty()) {
            try { Tasks.await(client.removeGeofences(pending(context)), 15, TimeUnit.SECONDS) } catch (_: Exception) { /* No active fences requested. */ }
            WorkManager.getInstance(context).cancelUniqueWork("commute-scan")
            return
        }
        check(!StateStore.state(context).getBoolean("demo")) { "데모 모드에서는 자동 시작을 사용하지 않습니다." }
        check(NativeAccess.configured(context) && NativeAccess.notifications(context)) { "Firebase와 알림 권한이 필요합니다." }
        check(NativeAccess.fine(context) && NativeAccess.background(context)) { "정확한 위치 및 항상 허용 권한이 필요합니다." }
        val fences = enabled.map { f ->
            val origin = f.getJSONObject("origin")
            Geofence.Builder().setRequestId(f.getString("id"))
                .setCircularRegion(origin.getDouble("latitude"), origin.getDouble("longitude"), 300f)
                .setExpirationDuration(Geofence.NEVER_EXPIRE)
                .setTransitionTypes(Geofence.GEOFENCE_TRANSITION_DWELL).setLoiteringDelay(60_000)
                .setNotificationResponsiveness(60_000).build()
        }
        Tasks.await(client.removeGeofences(pending(context)), 15, TimeUnit.SECONDS)
        val request = GeofencingRequest.Builder().setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_DWELL).addGeofences(fences).build()
        Tasks.await(client.addGeofences(request, pending(context)), 15, TimeUnit.SECONDS)
        val periodic = PeriodicWorkRequestBuilder<CommuteWorker>(15, TimeUnit.MINUTES)
            .setInitialDelay(15, TimeUnit.MINUTES)
            .setInputData(workDataOf("action" to "scan"))
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("commute-scan", ExistingPeriodicWorkPolicy.UPDATE, periodic)
        StateStore.error(context, "")
    }
}

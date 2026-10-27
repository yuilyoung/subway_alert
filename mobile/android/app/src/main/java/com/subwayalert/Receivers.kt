package com.subwayalert

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.work.*
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingEvent
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class GeofenceReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val event = GeofencingEvent.fromIntent(intent) ?: return
        if (event.hasError()) { StateStore.error(context, "위치 감지 오류: ${event.errorCode}"); return }
        if (event.geofenceTransition != Geofence.GEOFENCE_TRANSITION_DWELL) return
        val data = Data.Builder().putString("action", "scan")
        event.triggeringLocation?.let { data.putDouble("latitude", it.latitude).putDouble("longitude", it.longitude)
            .putDouble("accuracy", it.accuracy.toDouble()).putLong("time", it.time) }
        WorkManager.getInstance(context).enqueueUniqueWork("commute-entry", ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<CommuteWorker>().setInputData(data.build())
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
    }
}
class RestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in listOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED)) return
        WorkManager.getInstance(context).enqueueUniqueWork("restore-geofences", ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<CommuteWorker>().setInputData(workDataOf("action" to "restore")).build())
    }
}
class SubwayMessagingService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) { AlertNotifications.arrival(this, message.data) }
    override fun onNewToken(token: String) {
        WorkManager.getInstance(this).enqueueUniqueWork("refresh-device-token", ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<CommuteWorker>().setInputData(workDataOf("action" to "token"))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
    }
}

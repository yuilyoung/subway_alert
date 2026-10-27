package com.subwayalert

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.work.*
import com.facebook.react.BaseReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.module.annotations.ReactModule
import com.facebook.react.module.model.ReactModuleInfo
import com.facebook.react.module.model.ReactModuleInfoProvider
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.google.android.gms.tasks.Tasks
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONObject

@ReactModule(name = SubwayModule.NAME)
class SubwayModule(private val context: ReactApplicationContext) : NativeSubwaySpec(context) {
    companion object { const val NAME = "Subway"; private val executor = Executors.newSingleThreadExecutor() }
    override fun getName() = NAME
    private fun run(promise: Promise, block: () -> Any?) {
        executor.execute { try { promise.resolve(block()) } catch (e: Exception) { promise.reject("SUBWAY_ERROR", e.message ?: "작업에 실패했습니다.", e) } }
    }
    override fun getState(promise: Promise) = run(promise) { StateStore.state(context).toString() }
    override fun saveFavorites(json: String, promise: Promise) = run(promise) { StateStore.saveFavorites(context, json); true }
    override fun configure(baseUrl: String, demo: Boolean, promise: Promise) = run(promise) {
        StateStore.configure(context, baseUrl, demo); Geofences.sync(context); true
    }
    override fun identity(promise: Promise) = run(promise) { NativeAccess.identity(context).toString() }
    override fun setActiveSession(id: String, promise: Promise) = run(promise) { StateStore.setSession(context, id); true }
    override fun clearActiveSession(id: String, promise: Promise) = run(promise) { StateStore.clearSession(context, id); true }
    override fun syncGeofences(promise: Promise) = run(promise) { Geofences.sync(context); true }
    override fun capabilities(promise: Promise) = run(promise) { NativeAccess.capabilities(context).toString() }
    override fun location(promise: Promise) = run(promise) {
        check(NativeAccess.fine(context)) { "정확한 위치 권한이 필요합니다." }
        val source = CancellationTokenSource()
        try {
            val location = Tasks.await(LocationServices.getFusedLocationProviderClient(context)
                .getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, source.token), 15, TimeUnit.SECONDS)
                ?: error("현재 위치를 확인하지 못했습니다. 지상에서 다시 시도하세요.")
            JSONObject().put("latitude", location.latitude).put("longitude", location.longitude)
                .put("accuracy", location.accuracy).put("ageMillis", System.currentTimeMillis() - location.time).toString()
        } finally { source.cancel() }
    }
    override fun demoNotification(promise: Promise) = run(promise) {
        check(NativeAccess.notifications(context)) { "알림 권한을 허용하세요." }
        WorkManager.getInstance(context).enqueueUniqueWork("demo-notification", ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<CommuteWorker>().setInputData(workDataOf("action" to "demo"))
                .setInitialDelay(10, TimeUnit.SECONDS).build())
        true
    }
    override fun openSettings() {
        context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
class SubwayPackage : BaseReactPackage() {
    override fun getModule(name: String, reactContext: ReactApplicationContext): NativeModule? = if (name == SubwayModule.NAME) SubwayModule(reactContext) else null
    override fun getReactModuleInfoProvider() = ReactModuleInfoProvider {
        mapOf(SubwayModule.NAME to ReactModuleInfo(SubwayModule.NAME, SubwayModule.NAME, false, false, false, true))
    }
}

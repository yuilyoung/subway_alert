package com.subwayalert

import android.content.Context
import java.net.URI
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

object StateStore {
    fun prefs(context: Context) = context.getSharedPreferences("subway-alert", Context.MODE_PRIVATE)
    @Synchronized fun state(context: Context): JSONObject {
        val p = prefs(context)
        var install = p.getString("installId", null)
        if (install == null) {
            install = UUID.randomUUID().toString()
            check(p.edit().putString("installId", install).commit())
        }
        return JSONObject().put("installId", install)
            .put("baseUrl", p.getString("baseUrl", "http://10.0.2.2:8080"))
            .put("demo", p.getBoolean("demo", true))
            .put("sessionId", p.getString("sessionId", ""))
            .put("favorites", JSONArray(p.getString("favorites", "[]")))
            .put("autoError", p.getString("autoError", ""))
    }
    fun favorites(context: Context): List<JSONObject> {
        val array = JSONArray(prefs(context).getString("favorites", "[]"))
        return (0 until array.length()).map { array.getJSONObject(it) }
    }
    @Synchronized fun saveFavorites(context: Context, value: String) {
        require(value.length <= 32_768) { "즐겨찾기 데이터가 너무 큽니다." }
        val array = JSONArray(value)
        require(array.length() <= 5) { "즐겨찾기는 최대 5개입니다." }
        val ids = mutableSetOf<String>()
        val routes = mutableSetOf<String>()
        for (i in 0 until array.length()) {
            val f = array.getJSONObject(i)
            val id = f.getString("id")
            require(id.matches(Regex("[A-Za-z0-9_-]{1,100}")) && ids.add(id)) { "즐겨찾기 ID가 올바르지 않습니다." }
            require(f.getString("label").trim().length in 1..40) { "즐겨찾기 이름을 확인하세요." }
            val from = f.getJSONObject("origin")
            val to = f.getJSONObject("destination")
            require(from.getString("id").isNotBlank() && to.getString("id").isNotBlank()) { "역을 선택하세요." }
            require(from.getString("id") != to.getString("id") && from.getString("lineId") == to.getString("lineId")) { "동일 호선의 서로 다른 역을 선택하세요." }
            require(f.getString("direction") in listOf("0", "1")) { "방향을 확인하세요." }
            require(routes.add("${from.getString("id")}|${to.getString("id")}|${f.getString("direction")}")) { "이미 등록된 경로입니다." }
            CommuteWindow.validate(days(f), f.getString("start"), f.getString("end"))
            if (f.getBoolean("enabled")) {
                val lat = from.optDouble("latitude", Double.NaN)
                val lon = from.optDouble("longitude", Double.NaN)
                require(lat.isFinite() && lat in -90.0..90.0 && lon.isFinite() && lon in -180.0..180.0) { "출발역 좌표가 필요합니다." }
            }
        }
        val p = prefs(context)
        val editor = p.edit().putString("favorites", array.toString())
        favorites(context).forEach { if (it.getString("id") !in ids) editor.remove("fired:${it.getString("id")}") }
        check(editor.commit()) { "즐겨찾기를 저장하지 못했습니다." }
    }
    fun days(f: JSONObject): List<Int> {
        val days = f.getJSONArray("days")
        return (0 until days.length()).map { days.getInt(it) }
    }
    @Synchronized fun configure(context: Context, baseUrl: String, demo: Boolean) {
        require(prefs(context).getString("sessionId", "").isNullOrEmpty()) { "진행 중인 추적을 먼저 종료하세요." }
        val uri = URI(baseUrl.trim())
        require(baseUrl.length <= 256 && uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null) { "서버 주소를 확인하세요." }
        if (demo) {
            require(BuildConfig.ALLOW_LOCAL_HTTP && uri.host in listOf("localhost", "127.0.0.1", "10.0.2.2") && uri.scheme in listOf("http", "https")) { "데모 서버는 개발 빌드의 로컬 주소만 허용합니다." }
        } else require(uri.scheme == "https") { "실사용 서버는 HTTPS 주소여야 합니다." }
        val disabled = JSONArray()
        favorites(context).forEach { disabled.put(it.put("enabled", false)) }
        check(prefs(context).edit().putString("baseUrl", baseUrl.trim().trimEnd('/')).putBoolean("demo", demo)
            .putString("favorites", disabled.toString()).putString("autoError", "").commit())
    }
    @Synchronized fun setSession(context: Context, id: String) {
        require(id.length == 36); UUID.fromString(id)
        check(prefs(context).edit().putString("sessionId", id).commit())
    }
    @Synchronized fun clearSession(context: Context, id: String) {
        if (prefs(context).getString("sessionId", "") == id) {
            check(prefs(context).edit().remove("sessionId").commit())
            AlertNotifications.clear(context, id)
        }
    }
    fun error(context: Context, text: String) { prefs(context).edit().putString("autoError", text.take(300)).apply() }
}

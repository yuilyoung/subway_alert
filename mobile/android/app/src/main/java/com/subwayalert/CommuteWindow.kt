package com.subwayalert

import java.time.LocalTime
import java.time.ZonedDateTime

/** Pure rules shared by geofence callbacks and periodic recovery checks. */
object CommuteWindow {
    private val pattern = Regex("(?:[01]\\d|2[0-3]):[0-5]\\d")
    fun validate(days: List<Int>, start: String, end: String) {
        require(days.isNotEmpty() && days.distinct().size == days.size && days.all { it in 1..7 }) { "Invalid weekdays" }
        require(pattern.matches(start) && pattern.matches(end) && start != end) { "Invalid commute time window" }
    }
    fun serviceDate(days: List<Int>, start: String, end: String, now: ZonedDateTime, last: String?): String? {
        validate(days, start, end)
        val begin = LocalTime.parse(start)
        val finish = LocalTime.parse(end)
        val time = now.toLocalTime()
        val date = if (begin < finish) {
            if (time < begin || time >= finish) return null
            now.toLocalDate()
        } else {
            when {
                time >= begin -> now.toLocalDate()
                time < finish -> now.toLocalDate().minusDays(1)
                else -> return null
            }
        }
        return date.toString().takeIf { date.dayOfWeek.value in days && it != last }
    }
}

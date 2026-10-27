import com.subwayalert.CommuteWindow
import java.time.ZonedDateTime

fun main() {
    var checks = 0
    fun expect(expected: String?, days: List<Int>, start: String, end: String, now: String, last: String? = null) {
        val actual = CommuteWindow.serviceDate(days, start, end, ZonedDateTime.parse(now), last)
        check(expected == actual) { "Expected $expected, got $actual at $now" }; checks++
    }
    expect("2026-10-27", listOf(1,2,3,4,5), "07:00", "10:00", "2026-10-27T07:00:00+09:00[Asia/Seoul]")
    expect(null, listOf(1,2,3,4,5), "07:00", "10:00", "2026-10-27T10:00:00+09:00[Asia/Seoul]")
    expect(null, listOf(1,2,3,4,5), "07:00", "10:00", "2026-10-27T06:59:59+09:00[Asia/Seoul]")
    expect(null, listOf(1,2,3,4,5), "07:00", "10:00", "2026-10-31T08:00:00+09:00[Asia/Seoul]")
    expect(null, listOf(1,2,3,4,5), "07:00", "10:00", "2026-10-27T08:00:00+09:00[Asia/Seoul]", "2026-10-27")
    expect("2026-10-30", listOf(5), "23:00", "02:00", "2026-10-31T00:30:00+09:00[Asia/Seoul]")
    expect("2026-10-30", listOf(5), "23:00", "02:00", "2026-10-30T23:00:00+09:00[Asia/Seoul]")
    expect(null, listOf(5), "23:00", "02:00", "2026-10-31T02:00:00+09:00[Asia/Seoul]")
    expect(null, listOf(6), "23:00", "02:00", "2026-10-31T01:00:00+09:00[Asia/Seoul]")
    expect(null, listOf(5), "23:00", "02:00", "2026-10-30T22:59:00+09:00[Asia/Seoul]")
    expect(null, listOf(5), "23:00", "02:00", "2026-10-31T01:00:00+09:00[Asia/Seoul]", "2026-10-30")
    for ((start,end) in listOf("24:00" to "01:00", "7:00" to "10:00", "07:00" to "07:00")) {
        try { CommuteWindow.serviceDate(listOf(1),start,end,ZonedDateTime.now(),null); error("Invalid schedule accepted") }
        catch (expected: IllegalArgumentException) { checks++ }
    }
    println("CommuteWindow: $checks checks passed")
}

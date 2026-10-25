package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.data.TaskBody
import com.crowdersoup.vtodo.data.taskPayload
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TaskPayloadTest {
    private val base = TaskBody(
        title = "Water plants",
        notes = "Written on the website",
        dueDate = "2026-10-24",
        dueTime = "09:00",
        tags = listOf("home"),
        recurrenceDays = 3,
        recurrenceFrom = "completion",
    )

    @Test
    fun withoutBeforeSendsEveryField() {
        val json = taskPayload(base, null)
        assertEquals(
            setOf("title", "notes", "due_date", "due_time", "tags", "recurrence_days", "recurrence_from"),
            json.keys,
        )
    }

    @Test
    fun sendsOnlyTheChangedTitle() {
        val json = taskPayload(base.copy(title = "Water the plants"), base)
        assertEquals(setOf("title"), json.keys)
        assertEquals(JsonPrimitive("Water the plants"), json["title"])
    }

    @Test
    fun nothingChangedSendsNothing() {
        assertTrue(taskPayload(base, base).isEmpty())
    }

    @Test
    fun clearingTheDateAlsoClearsTheTime() {
        val json = taskPayload(base.copy(dueDate = null), base)
        assertEquals(setOf("due_date", "due_time"), json.keys)
        assertEquals(JsonNull, json["due_date"])
        assertEquals(JsonNull, json["due_time"])
    }

    @Test
    fun movingTheDateKeepsTheTimeOutOfThePatch() {
        val json = taskPayload(base.copy(dueDate = "2026-10-25"), base)
        assertEquals(setOf("due_date"), json.keys)
    }

    @Test
    fun clearingRecurrenceSendsNull() {
        val json = taskPayload(base.copy(recurrenceDays = null), base)
        assertEquals(setOf("recurrence_days"), json.keys)
        assertEquals(JsonNull, json["recurrence_days"])
    }
}

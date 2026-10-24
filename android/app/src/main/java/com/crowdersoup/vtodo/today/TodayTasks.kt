package com.crowdersoup.vtodo.today

import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale

data class TaskRecord(
    val id: Long,
    val title: String,
    val status: String,
    val dueDate: String?,
    val dueTime: String?,
    val isArchived: Boolean,
    val completedAt: String?,
    val sortOrder: Int,
    val notes: String = "",
)

data class StatusRecord(
    val slug: String,
    val name: String,
    val sortOrder: Int,
    val isDone: Boolean,
)

data class OpenTask(
    val id: Long,
    val title: String,
    val statusSlug: String,
    val statusName: String,
    val dueDate: LocalDate?,
    val dueTime: LocalTime?,
    val notes: String,
    val sortOrder: Int,
)

data class TodayTask(
    val id: Long,
    val title: String,
    val dueDate: LocalDate,
    val dueTime: LocalTime?,
    val sortOrder: Int,
)

object TodayTasks {
    fun select(tasks: List<TaskRecord>, doneSlugs: Set<String>, today: LocalDate): List<TodayTask> {
        return tasks.mapNotNull { task -> toTodayTask(task, doneSlugs, today) }
            .sortedWith(
                compareBy<TodayTask> { it.dueDate }
                    .thenBy { it.dueTime != null }
                    .thenBy { it.dueTime ?: LocalTime.MIN }
                    .thenBy { it.sortOrder }
                    .thenBy { it.id },
            )
    }

    private fun toTodayTask(task: TaskRecord, doneSlugs: Set<String>, today: LocalDate): TodayTask? {
        if (task.isArchived || !task.completedAt.isNullOrBlank() || task.status in doneSlugs) {
            return null
        }
        val due = task.dueDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return null
        if (due > today) return null
        val time = task.dueTime?.takeIf { it.isNotBlank() }?.let {
            runCatching { LocalTime.parse(it) }.getOrNull()
        }
        return TodayTask(
            id = task.id,
            title = task.title,
            dueDate = due,
            dueTime = time,
            sortOrder = task.sortOrder,
        )
    }
}

object OpenTasks {
    fun select(tasks: List<TaskRecord>, statuses: List<StatusRecord>): List<OpenTask> {
        val done = statuses.filter { it.isDone }.map { it.slug }.toSet()
        return tasks.mapNotNull { task ->
            if (task.isArchived || !task.completedAt.isNullOrBlank() || task.status in done) {
                null
            } else {
                from(task, statuses)
            }
        }.sortedWith(openOrder)
    }

    fun from(task: TaskRecord, statuses: List<StatusRecord>): OpenTask {
        val status = statuses.firstOrNull { it.slug == task.status }
        return OpenTask(
            id = task.id,
            title = task.title,
            statusSlug = task.status,
            statusName = status?.name?.takeIf { it.isNotBlank() } ?: task.status,
            dueDate = task.dueDate?.takeIf { it.isNotBlank() }?.let { runCatching { LocalDate.parse(it) }.getOrNull() },
            dueTime = task.dueTime?.takeIf { it.isNotBlank() }?.let { runCatching { LocalTime.parse(it) }.getOrNull() },
            notes = task.notes,
            sortOrder = task.sortOrder,
        )
    }

    private val openOrder = compareBy<OpenTask> { it.dueDate == null }
        .thenBy { it.dueDate ?: LocalDate.MAX }
        .thenBy { it.dueTime != null }
        .thenBy { it.dueTime ?: LocalTime.MIN }
        .thenBy { it.sortOrder }
        .thenBy { it.id }
}

fun parseDueInput(text: String): Result<LocalDate?> {
    val trimmed = text.trim()
    if (trimmed.isEmpty()) return Result.success(null)
    val date = runCatching { LocalDate.parse(trimmed) }.getOrElse {
        return Result.failure(IllegalArgumentException("Use a date like 2026-10-24."))
    }
    return Result.success(date)
}

fun dueLabel(task: TodayTask, today: LocalDate, locale: Locale): String {
    val day = if (task.dueDate < today) {
        "Overdue · " + task.dueDate.format(DateTimeFormatter.ofPattern("MMM d", locale))
    } else {
        "Today"
    }
    val clock = task.dueTime?.format(DateTimeFormatter.ofPattern("h:mm a", locale))
    return if (clock == null) day else "$day · $clock"
}

fun openLabel(task: OpenTask, today: LocalDate, locale: Locale): String {
    val day = when {
        task.dueDate == null -> "No date"
        task.dueDate < today -> "Overdue · " + task.dueDate.format(DateTimeFormatter.ofPattern("MMM d", locale))
        task.dueDate == today -> "Today"
        else -> task.dueDate.format(DateTimeFormatter.ofPattern("MMM d", locale))
    }
    val clock = task.dueTime?.format(DateTimeFormatter.ofPattern("h:mm a", locale))
    return if (clock == null) "${task.statusName} · $day" else "${task.statusName} · $day · $clock"
}

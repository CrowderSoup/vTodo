package com.crowdersoup.vtodo.today

import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale

const val RECURRENCE_FROM_COMPLETION = "completion"
const val RECURRENCE_FROM_DUE_DATE = "due_date"

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
    val tags: List<String> = emptyList(),
    val recurrenceDays: Int? = null,
    val recurrenceFrom: String = RECURRENCE_FROM_COMPLETION,
)

data class StatusRecord(
    val slug: String,
    val name: String,
    val sortOrder: Int,
    val isDone: Boolean,
    val color: String = "",
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
    val statusColor: String = "",
    val tags: List<String> = emptyList(),
    val recurrenceDays: Int? = null,
    val recurrenceFrom: String = RECURRENCE_FROM_COMPLETION,
)

data class TodayTask(
    val id: Long,
    val title: String,
    val dueDate: LocalDate,
    val dueTime: LocalTime?,
    val sortOrder: Int,
    val statusName: String = "",
    val statusColor: String = "",
    val tags: List<String> = emptyList(),
    val recurrenceDays: Int? = null,
)

object TodayTasks {
    fun select(tasks: List<TaskRecord>, statuses: List<StatusRecord>, today: LocalDate): List<TodayTask> {
        val doneSlugs = statuses.filter { it.isDone }.map { it.slug }.toSet()
        return tasks.mapNotNull { task -> toTodayTask(task, statuses, doneSlugs, today) }
            .sortedWith(
                compareBy<TodayTask> { it.dueDate }
                    .thenBy { it.dueTime != null }
                    .thenBy { it.dueTime ?: LocalTime.MIN }
                    .thenBy { it.sortOrder }
                    .thenBy { it.id },
            )
    }

    private fun toTodayTask(
        task: TaskRecord,
        statuses: List<StatusRecord>,
        doneSlugs: Set<String>,
        today: LocalDate,
    ): TodayTask? {
        if (task.isArchived || !task.completedAt.isNullOrBlank() || task.status in doneSlugs) {
            return null
        }
        val due = task.dueDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return null
        if (due > today) return null
        val time = task.dueTime?.takeIf { it.isNotBlank() }?.let {
            runCatching { LocalTime.parse(it) }.getOrNull()
        }
        val status = statuses.firstOrNull { it.slug == task.status }
        return TodayTask(
            id = task.id,
            title = task.title,
            dueDate = due,
            dueTime = time,
            sortOrder = task.sortOrder,
            statusName = status?.name?.takeIf { it.isNotBlank() } ?: task.status,
            statusColor = status?.color.orEmpty(),
            tags = task.tags,
            recurrenceDays = task.recurrenceDays?.takeIf { it >= 1 },
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
            statusColor = status?.color.orEmpty(),
            tags = task.tags,
            recurrenceDays = task.recurrenceDays?.takeIf { it >= 1 },
            recurrenceFrom = normalizeRecurrenceFrom(task.recurrenceFrom),
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

fun openDateLabel(task: OpenTask, today: LocalDate, locale: Locale): String? {
    val due = task.dueDate ?: return null
    return dueChipLabel(due, task.dueTime, today, locale)
}

fun dueChipLabel(due: LocalDate, time: LocalTime?, today: LocalDate, locale: Locale): String {
    val day = when {
        due < today -> "Overdue · " + due.format(DateTimeFormatter.ofPattern("MMM d", locale))
        due == today -> "Today"
        else -> due.format(DateTimeFormatter.ofPattern("MMM d", locale))
    }
    val clock = time?.format(DateTimeFormatter.ofPattern("h:mm a", locale))
    return if (clock == null) day else "$day · $clock"
}

private val statusColorPattern = Regex("""^#([0-9A-Fa-f]{6})$""")

fun statusColorArgb(hex: String): Long? {
    val match = statusColorPattern.matchEntire(hex.trim()) ?: return null
    return match.groupValues[1].toLong(16) or 0xFF000000L
}

fun normalizeRecurrenceFrom(value: String): String {
    return if (value == RECURRENCE_FROM_DUE_DATE) RECURRENCE_FROM_DUE_DATE else RECURRENCE_FROM_COMPLETION
}

fun parseRecurrenceDays(text: String): Result<Int?> {
    val trimmed = text.trim()
    if (trimmed.isEmpty()) return Result.success(null)
    val days = trimmed.toIntOrNull()
    if (days == null || days !in 1..32_767) {
        return Result.failure(IllegalArgumentException("Use a number of days, like 7."))
    }
    return Result.success(days)
}

fun formatDueTime(time: LocalTime): String {
    val hour = time.hour.toString().padStart(2, '0')
    val minute = time.minute.toString().padStart(2, '0')
    return "$hour:$minute"
}

fun recurrenceLabel(days: Int): String {
    val unit = if (days == 1) "day" else "days"
    return "Repeats every $days $unit"
}

fun normalizeTags(tags: List<String>): List<String> {
    val seen = LinkedHashSet<String>()
    tags.forEach { tag ->
        tag.split(',').forEach { part ->
            val trimmed = part.trim()
            if (trimmed.isNotEmpty()) seen.add(trimmed)
        }
    }
    return seen.toList()
}

fun addTags(current: List<String>, raw: String): List<String> {
    val additions = normalizeTags(listOf(raw))
    if (additions.isEmpty()) return current
    val taken = current.mapTo(HashSet()) { it.lowercase() }
    val next = current.toMutableList()
    additions.forEach { tag ->
        if (taken.add(tag.lowercase())) next.add(tag)
    }
    return next
}

fun tagSuggestions(
    known: List<String>,
    selected: List<String>,
    query: String,
    limit: Int = 8,
): List<String> {
    val taken = selected.mapTo(HashSet()) { it.trim().lowercase() }
    val needle = query.trim().lowercase()
    val seen = HashSet<String>()
    val matches = ArrayList<String>(limit)
    for (tag in known) {
        val lower = tag.lowercase()
        if (lower in taken || !seen.add(lower)) continue
        if (needle.isNotEmpty() && needle !in lower) continue
        matches.add(tag)
        if (matches.size == limit) break
    }
    return matches
}

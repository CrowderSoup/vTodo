package com.crowdersoup.vtodo.data

import androidx.room.withTransaction
import com.crowdersoup.vtodo.today.OpenTask
import com.crowdersoup.vtodo.today.OpenTasks
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.TodayTasks
import com.crowdersoup.vtodo.today.formatDueTime
import com.crowdersoup.vtodo.today.normalizeRecurrenceFrom
import com.crowdersoup.vtodo.today.normalizeTags
import java.time.LocalDate
import java.time.LocalTime
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant
import kotlin.coroutines.cancellation.CancellationException

data class TaskWrite(
    val title: String,
    val notes: String,
    val dueDate: LocalDate?,
    val dueTime: LocalTime?,
    val tags: List<String>,
    val recurrenceDays: Int?,
    val recurrenceFrom: String,
)

data class TaskLists(
    val today: List<TodayTask> = emptyList(),
    val open: List<OpenTask> = emptyList(),
    val statuses: List<StatusRecord> = emptyList(),
)

class VtodoRepository(
    private val database: VtodoDatabase,
    private val api: VtodoApi,
    private val sessionStore: SessionStore,
    // Shown on the website under Settings → API → Signed-in devices.
    private val deviceName: String = "",
    // Queues a background sync for when the phone is back online.
    private val requestSync: () -> Unit = {},
) {
    private val mutex = Mutex()

    fun observeLists(): Flow<TaskLists> {
        return combine(database.taskDao().observe(), database.statusDao().observe()) { tasks, statuses ->
            val records = tasks.map { it.toRecord() }
            val statusRecords = statuses.map { it.toRecord() }
            TaskLists(
                today = TodayTasks.select(records, statusRecords, LocalDate.now()),
                open = OpenTasks.select(records, statusRecords),
                statuses = statusRecords.sortedBy { it.sortOrder },
            )
        }
    }

    fun observeToday(): Flow<List<TodayTask>> {
        return combine(database.taskDao().observe(), database.statusDao().observe()) { tasks, statuses ->
            TodayTasks.select(
                tasks.map { it.toRecord() },
                statuses.map { it.toRecord() },
                LocalDate.now(),
            )
        }
    }

    suspend fun todaySnapshot(today: LocalDate = LocalDate.now()): List<TodayTask> {
        val statuses = database.statusDao().all().map { it.toRecord() }
        return TodayTasks.select(database.taskDao().all().map { it.toRecord() }, statuses, today)
    }

    suspend fun findTask(id: Long): OpenTask? {
        val entity = database.taskDao().get(id) ?: return null
        if (entity.isArchived) return null
        return OpenTasks.from(entity.toRecord(), database.statusDao().all().map { it.toRecord() })
    }

    suspend fun signIn(baseUrl: String, token: String): Result<Unit> {
        val normalized = try {
            normalizeBaseUrl(baseUrl)
        } catch (e: IllegalArgumentException) {
            return Result.failure(e)
        }
        val trimmed = token.trim()
        if (trimmed.isEmpty()) {
            return Result.failure(IllegalArgumentException("API token is required."))
        }
        val session = Session(normalized, trimmed)
        return try {
            api.fetchStatuses(session)
            sessionStore.save(session)
            sync()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun signInWithGoogle(
        baseUrl: String,
        requestIdToken: suspend (serverClientId: String) -> String,
    ): Result<Unit> {
        val normalized = try {
            normalizeBaseUrl(baseUrl)
        } catch (e: IllegalArgumentException) {
            return Result.failure(e)
        }
        return try {
            val clientId = api.fetchGoogleClientId(normalized)
            val idToken = requestIdToken(clientId)
            val token = api.exchangeGoogleIdToken(normalized, idToken, deviceName)
            val session = Session(normalized, token)
            api.fetchStatuses(session)
            sessionStore.save(session)
            sync()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun sync(): Result<Unit> = attempt {
        withSession { pull(it) }
    }

    suspend fun createTask(input: TaskWrite): Result<Unit> {
        val body = input.toBody()
            ?: return Result.failure(IllegalArgumentException("A title is required."))
        return attempt {
            withSession { session ->
                api.createTask(session, body)
                refreshAfterWrite(session)
            }
        }
    }

    /**
     * Saves an edit. [baseline] is the task as it was when editing started;
     * only fields that differ from it are sent, so a stale copy on the phone
     * does not overwrite changes made elsewhere in the meantime.
     */
    suspend fun saveTask(taskId: Long, input: TaskWrite, baseline: TaskWrite): Result<Unit> {
        val body = input.toBody()
            ?: return Result.failure(IllegalArgumentException("A title is required."))
        val changes = taskPayload(body, baseline.toBody())
        return attempt {
            withSession { session ->
                if (changes.isNotEmpty()) api.patchTask(session, taskId, changes)
                refreshAfterWrite(session)
            }
        }
    }

    suspend fun deleteTask(taskId: Long): Result<Unit> = attempt {
        withSession { session ->
            api.deleteTask(session, taskId)
            refreshAfterWrite(session)
        }
    }

    suspend fun complete(taskId: Long): Result<Unit> {
        val done = database.statusDao().all()
            .filter { it.isDone }
            .minByOrNull { it.sortOrder }
            ?: return Result.failure(IllegalStateException("Add a completed status on the website first."))
        return move(taskId, done.slug)
    }

    suspend fun move(taskId: Long, statusSlug: String): Result<Unit> {
        var previous: TaskEntity? = null
        val result = attempt {
            withSession { session ->
                val status = database.statusDao().all().firstOrNull { it.slug == statusSlug }
                    ?: throw IllegalStateException("That status is not on this phone yet. Refresh and try again.")
                previous = database.taskDao().get(taskId)
                val existing = previous
                if (existing != null) {
                    val completedAt = if (status.isDone) {
                        existing.completedAt ?: Instant.now().toString()
                    } else {
                        null
                    }
                    database.taskDao().updateStatus(taskId, status.slug, completedAt)
                }
                api.moveTask(session, taskId, status.slug)
                refreshAfterWrite(session)
            }
        }
        if (result.isFailure) restore(taskId, previous)
        return result
    }

    /**
     * Clears the phone right away, then asks the server to revoke this
     * phone's token. If that request fails (offline), the token stays valid
     * until it is removed under Settings → API → Signed-in devices.
     */
    suspend fun signOut() {
        val session = mutex.withLock {
            sessionStore.current().also { clearLocal() }
        } ?: return
        try {
            api.signOut(session)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // Best effort; see above.
        }
    }

    /**
     * Runs [block] with the signed-in session, holding the same lock as
     * [signOut]. Reading the session inside the lock means work queued behind
     * a sign-out sees no session, instead of pulling the old account's tasks
     * back into the cleared database. A 401 means the server no longer
     * accepts this phone's token, so the phone signs itself out.
     */
    private suspend fun <T> withSession(block: suspend (Session) -> T): T = mutex.withLock {
        val session = sessionStore.current() ?: throw IllegalStateException("Sign in first.")
        try {
            block(session)
        } catch (e: VtodoApiException) {
            if (e.httpCode == 401 && sessionStore.current() == session) {
                clearLocal(SIGNED_OUT_BY_SERVER)
                throw VtodoApiException(401, SIGNED_OUT_BY_SERVER)
            }
            throw e
        }
    }

    /**
     * The write already reached the server. If reading the lists back fails
     * (the connection dropped in between), reporting the write as failed
     * would undo a move the server kept, or get a new task created twice on
     * retry. The phone's copy catches up on the queued sync instead.
     */
    private suspend fun refreshAfterWrite(session: Session) {
        try {
            pull(session)
        } catch (e: VtodoApiException) {
            if (e.httpCode == 401) throw e
            requestSync()
        }
    }

    private suspend fun <T> attempt(block: suspend () -> T): Result<T> {
        return try {
            Result.success(block())
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Callers hold [mutex]. */
    private suspend fun clearLocal(reason: String? = null) {
        sessionStore.clear(reason)
        database.withTransaction {
            database.taskDao().clear()
            database.statusDao().clear()
        }
    }

    private fun TaskWrite.toBody(): TaskBody? {
        val trimmed = title.trim()
        if (trimmed.isEmpty()) return null
        val time = if (dueDate == null) null else dueTime
        return TaskBody(
            title = trimmed,
            notes = notes,
            dueDate = dueDate?.toString(),
            dueTime = time?.let(::formatDueTime),
            tags = normalizeTags(tags),
            recurrenceDays = recurrenceDays?.takeIf { it >= 1 },
            recurrenceFrom = normalizeRecurrenceFrom(recurrenceFrom),
        )
    }

    private suspend fun pull(session: Session) {
        val tasks = api.fetchTasks(session)
        val statuses = api.fetchStatuses(session)
        database.withTransaction {
            database.taskDao().clear()
            database.statusDao().clear()
            database.taskDao().insertAll(tasks.map { it.toEntity() })
            database.statusDao().insertAll(statuses.map { it.toEntity() })
        }
    }

    private suspend fun restore(taskId: Long, previous: TaskEntity?) {
        if (sync().isSuccess) return
        // Offline: put the row back by hand. The next sync replaces the table.
        if (previous != null && sessionStore.current() != null) {
            database.taskDao().updateStatus(taskId, previous.status, previous.completedAt)
        }
    }

    private companion object {
        const val SIGNED_OUT_BY_SERVER =
            "The server signed this phone out. It may have been removed under Settings, API. Sign in again."
    }
}

package com.crowdersoup.vtodo.ui

import android.app.Activity as HostActivity
import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.crowdersoup.vtodo.MainActivity
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.data.GoogleSignIn
import com.crowdersoup.vtodo.data.TaskWrite
import com.crowdersoup.vtodo.today.OpenTask
import com.crowdersoup.vtodo.today.RECURRENCE_FROM_COMPLETION
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.normalizeRecurrenceFrom
import com.crowdersoup.vtodo.today.normalizeTags
import com.crowdersoup.vtodo.today.parseDueInput
import com.crowdersoup.vtodo.today.parseRecurrenceDays
import com.crowdersoup.vtodo.widget.refreshTodayWidget
import com.crowdersoup.vtodo.work.SyncScheduler
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalTime

enum class Section { Today, Open }

sealed interface Screen {
    data object List : Screen
    data object Task : Screen
    data object Edit : Screen
    data object NewTask : Screen
}

data class TaskDraft(
    val id: Long,
    val title: String,
    val notes: String,
    val dueDate: String,
    val dueTime: LocalTime?,
    val statusSlug: String,
    val tags: List<String>,
    val recurrenceDays: String = "",
    val recurrenceFrom: String = RECURRENCE_FROM_COMPLETION,
    // The task as the phone last saw it when this draft was opened. Saving
    // sends only what differs from it.
    val baseline: TaskWrite,
)

data class NewTaskDraft(
    val title: String = "",
    val notes: String = "",
    val dueDate: String = "",
    val dueTime: LocalTime? = null,
    val tags: List<String> = emptyList(),
    val recurrenceDays: String = "",
    val recurrenceFrom: String = RECURRENCE_FROM_COMPLETION,
)

data class AppUiState(
    val signedIn: Boolean = false,
    val section: Section = Section.Today,
    val today: List<TodayTask> = emptyList(),
    val open: List<OpenTask> = emptyList(),
    val statuses: List<StatusRecord> = emptyList(),
    val screen: Screen = Screen.List,
    val draft: TaskDraft? = null,
    val newTask: NewTaskDraft = NewTaskDraft(),
    val refreshing: Boolean = false,
    val saving: Boolean = false,
    val message: String? = null,
    val busy: Set<Long> = emptySet(),
    // Why the server signed this phone out, for the sign-in screen.
    val signedOutReason: String? = null,
)

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val graph = (app as VtodoApp).graph
    private val section = MutableStateFlow(Section.Today)
    private val screen = MutableStateFlow<Screen>(Screen.List)
    private val draft = MutableStateFlow<TaskDraft?>(null)
    private val newTask = MutableStateFlow(NewTaskDraft())
    private val refreshing = MutableStateFlow(false)
    private val saving = MutableStateFlow(false)
    private val message = MutableStateFlow<String?>(null)
    private val busy = MutableStateFlow<Set<Long>>(emptySet())

    // Survives rotation with this ViewModel, and is gone after process death.
    private var launchIntentConsumed = false

    val state: StateFlow<AppUiState> = combine(
        combine(graph.sessionStore.session, graph.sessionStore.signedOutReason) { session, reason ->
            session to reason
        },
        graph.repository.observeLists(),
        combine(section, screen, draft, newTask) { section, screen, draft, newTask ->
            Chrome(section, screen, draft, newTask)
        },
        combine(refreshing, saving, message, busy) { refreshing, saving, message, busy ->
            Activity(refreshing, saving, message, busy)
        },
    ) { (session, signedOutReason), lists, chrome, activity ->
        AppUiState(
            signedIn = session != null,
            signedOutReason = signedOutReason,
            section = chrome.section,
            today = lists.today,
            open = lists.open,
            statuses = lists.statuses,
            screen = chrome.screen,
            draft = chrome.draft,
            newTask = chrome.newTask,
            refreshing = activity.refreshing,
            saving = activity.saving,
            message = activity.message,
            busy = activity.busy,
        )
    }.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        AppUiState(signedIn = graph.sessionStore.current() != null),
    )

    init {
        // The repository signs the phone out by itself when the server rejects
        // the token, so the open task can belong to the old session.
        viewModelScope.launch {
            graph.sessionStore.session.collect { session ->
                if (session == null) {
                    screen.value = Screen.List
                    draft.value = null
                }
            }
        }
    }

    fun signIn(baseUrl: String, token: String) {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            message.value = null
            try {
                finishSignIn(graph.repository.signIn(baseUrl, token))
            } finally {
                refreshing.value = false
            }
        }
    }

    fun signInWithGoogle(baseUrl: String, activity: HostActivity) {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            message.value = null
            try {
                val result = graph.repository.signInWithGoogle(baseUrl) { clientId ->
                    GoogleSignIn.requestIdToken(activity, clientId)
                }
                finishSignIn(result)
            } finally {
                refreshing.value = false
            }
        }
    }

    private suspend fun finishSignIn(result: Result<Unit>) {
        result.onSuccess {
            SyncScheduler.onSignedIn(getApplication())
            refreshTodayWidget(getApplication())
        }.onFailure { error ->
            message.value = error.message
        }
    }

    fun refresh() {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            message.value = null
            graph.repository.sync()
                .onFailure { message.value = it.message }
            refreshTodayWidget(getApplication())
            refreshing.value = false
        }
    }

    fun showSection(next: Section) {
        section.value = next
    }

    fun showList() {
        screen.value = Screen.List
        draft.value = null
        message.value = null
    }

    fun startNewTask() {
        newTask.value = NewTaskDraft()
        message.value = null
        screen.value = Screen.NewTask
    }

    fun startEditing() {
        if (draft.value == null) return
        message.value = null
        screen.value = Screen.Edit
    }

    fun backFromEditor() {
        if (screen.value == Screen.NewTask || draft.value == null) {
            showList()
            return
        }
        showTask(draft.value?.id ?: return)
    }

    fun updateNewTask(
        title: String? = null,
        notes: String? = null,
        dueDate: String? = null,
        dueTime: LocalTime? = null,
        clearDueTime: Boolean = false,
        tags: List<String>? = null,
        recurrenceDays: String? = null,
        recurrenceFrom: String? = null,
    ) {
        val current = newTask.value
        val nextDate = dueDate ?: current.dueDate
        newTask.value = current.copy(
            title = title ?: current.title,
            notes = notes ?: current.notes,
            dueDate = nextDate,
            dueTime = nextDueTime(nextDate, current.dueTime, dueTime, clearDueTime),
            tags = tags?.let(::normalizeTags) ?: current.tags,
            recurrenceDays = recurrenceDays ?: current.recurrenceDays,
            recurrenceFrom = recurrenceFrom?.let(::normalizeRecurrenceFrom) ?: current.recurrenceFrom,
        )
    }

    fun shouldApplyLaunchIntent(restoredInstance: Boolean): Boolean =
        !launchIntentConsumed || !restoredInstance

    fun openFromIntent(intent: Intent?) {
        launchIntentConsumed = true
        if (intent?.action != MainActivity.ACTION_OPEN) return
        if (!intent.hasExtra(MainActivity.EXTRA_TASK_ID)) {
            showList()
            return
        }
        val id = intent.getLongExtra(MainActivity.EXTRA_TASK_ID, -1L)
        intent.removeExtra(MainActivity.EXTRA_TASK_ID)
        if (id > 0) showTask(id)
    }

    fun showTask(id: Long) {
        val session = graph.sessionStore.current() ?: return
        viewModelScope.launch {
            val task = graph.repository.findTask(id)
            // A sign-out can land while the lookup is suspended. Writing the
            // task back would reopen the previous account on the next sign-in.
            if (graph.sessionStore.current() != session) return@launch
            if (task == null) {
                message.value = "That task isn't on this phone yet. Refresh and try again."
                return@launch
            }
            draft.value = task.toDraft()
            message.value = null
            screen.value = Screen.Task
        }
    }

    fun updateDraft(
        title: String? = null,
        notes: String? = null,
        dueDate: String? = null,
        dueTime: LocalTime? = null,
        clearDueTime: Boolean = false,
        tags: List<String>? = null,
        recurrenceDays: String? = null,
        recurrenceFrom: String? = null,
    ) {
        val current = draft.value ?: return
        val nextDate = dueDate ?: current.dueDate
        draft.value = current.copy(
            title = title ?: current.title,
            notes = notes ?: current.notes,
            dueDate = nextDate,
            dueTime = nextDueTime(nextDate, current.dueTime, dueTime, clearDueTime),
            tags = tags?.let(::normalizeTags) ?: current.tags,
            recurrenceDays = recurrenceDays ?: current.recurrenceDays,
            recurrenceFrom = recurrenceFrom?.let(::normalizeRecurrenceFrom) ?: current.recurrenceFrom,
        )
    }

    fun saveNewTask() {
        if (saving.value) return
        val draft = newTask.value
        val schedule = scheduleFrom(draft.dueDate, draft.dueTime, draft.recurrenceDays, draft.recurrenceFrom) ?: return
        viewModelScope.launch {
            saving.value = true
            message.value = null
            val result = graph.repository.createTask(draft.toWrite(schedule))
            result.onSuccess {
                refreshTodayWidget(getApplication())
                section.value = if (schedule.dueDate != null && !schedule.dueDate.isAfter(LocalDate.now())) {
                    Section.Today
                } else {
                    Section.Open
                }
                screen.value = Screen.List
            }.onFailure { message.value = it.message }
            saving.value = false
        }
    }

    fun saveTask() {
        if (saving.value) return
        val current = draft.value ?: return
        val session = graph.sessionStore.current() ?: return
        val schedule = scheduleFrom(current.dueDate, current.dueTime, current.recurrenceDays, current.recurrenceFrom) ?: return
        viewModelScope.launch {
            saving.value = true
            message.value = null
            val result = graph.repository.saveTask(current.id, current.toWrite(schedule), current.baseline)
            if (graph.sessionStore.current() != session) {
                result.onFailure { message.value = it.message }
                saving.value = false
                return@launch
            }
            result.onSuccess {
                refreshTodayWidget(getApplication())
                val fresh = graph.repository.findTask(current.id)
                if (graph.sessionStore.current() != session) return@onSuccess
                if (fresh == null) {
                    showList()
                } else {
                    draft.value = fresh.toDraft()
                    screen.value = Screen.Task
                }
            }.onFailure { message.value = it.message }
            saving.value = false
        }
    }

    fun deleteTask() {
        if (saving.value) return
        val current = draft.value ?: return
        viewModelScope.launch {
            saving.value = true
            message.value = null
            val result = graph.repository.deleteTask(current.id)
            result.onSuccess {
                refreshTodayWidget(getApplication())
                showList()
            }.onFailure { message.value = it.message }
            saving.value = false
        }
    }

    fun moveTask(statusSlug: String) {
        val current = draft.value ?: return
        if (current.statusSlug == statusSlug || current.id in busy.value) return
        viewModelScope.launch {
            busy.value = busy.value + current.id
            message.value = null
            val result = graph.repository.move(current.id, statusSlug)
            refreshTodayWidget(getApplication())
            result.onSuccess {
                draft.value = draft.value?.copy(statusSlug = statusSlug)
            }.onFailure { message.value = it.message ?: "Couldn't move that task." }
            busy.value = busy.value - current.id
        }
    }

    fun complete(taskId: Long) {
        if (taskId in busy.value) return
        viewModelScope.launch {
            busy.value = busy.value + taskId
            val result = graph.repository.complete(taskId)
            refreshTodayWidget(getApplication())
            result.onFailure { message.value = it.message ?: "Couldn't complete that task." }
            busy.value = busy.value - taskId
        }
    }

    private fun scheduleFrom(
        dueText: String,
        dueTime: LocalTime?,
        recurrenceText: String,
        recurrenceFrom: String,
    ): Schedule? {
        val due = parseDueInput(dueText).getOrElse {
            message.value = it.message
            return null
        }
        val days = parseRecurrenceDays(recurrenceText).getOrElse {
            message.value = it.message
            return null
        }
        return Schedule(
            dueDate = due,
            dueTime = if (due == null) null else dueTime,
            recurrenceDays = days,
            recurrenceFrom = normalizeRecurrenceFrom(recurrenceFrom),
        )
    }

    fun signOut() {
        viewModelScope.launch {
            SyncScheduler.cancel(getApplication())
            graph.repository.signOut()
            message.value = null
            draft.value = null
            screen.value = Screen.List
            refreshTodayWidget(getApplication())
        }
    }

    private data class Chrome(
        val section: Section,
        val screen: Screen,
        val draft: TaskDraft?,
        val newTask: NewTaskDraft,
    )

    private data class Activity(
        val refreshing: Boolean,
        val saving: Boolean,
        val message: String?,
        val busy: Set<Long>,
    )
}

private fun OpenTask.toDraft() = TaskDraft(
    id = id,
    title = title,
    notes = notes,
    dueDate = dueDate?.toString().orEmpty(),
    dueTime = dueTime,
    statusSlug = statusSlug,
    tags = tags,
    recurrenceDays = recurrenceDays?.toString().orEmpty(),
    recurrenceFrom = normalizeRecurrenceFrom(recurrenceFrom),
    baseline = TaskWrite(
        title = title,
        notes = notes,
        dueDate = dueDate,
        dueTime = dueTime,
        tags = tags,
        recurrenceDays = recurrenceDays,
        recurrenceFrom = normalizeRecurrenceFrom(recurrenceFrom),
    ),
)

private data class Schedule(
    val dueDate: LocalDate?,
    val dueTime: LocalTime?,
    val recurrenceDays: Int?,
    val recurrenceFrom: String,
)

private fun nextDueTime(
    nextDate: String,
    current: LocalTime?,
    dueTime: LocalTime?,
    clearDueTime: Boolean,
): LocalTime? {
    return when {
        nextDate.isBlank() || clearDueTime -> null
        dueTime != null -> dueTime
        else -> current
    }
}

private fun NewTaskDraft.toWrite(schedule: Schedule) = TaskWrite(
    title = title,
    notes = notes,
    dueDate = schedule.dueDate,
    dueTime = schedule.dueTime,
    tags = tags,
    recurrenceDays = schedule.recurrenceDays,
    recurrenceFrom = schedule.recurrenceFrom,
)

private fun TaskDraft.toWrite(schedule: Schedule) = TaskWrite(
    title = title,
    notes = notes,
    dueDate = schedule.dueDate,
    dueTime = schedule.dueTime,
    tags = tags,
    recurrenceDays = schedule.recurrenceDays,
    recurrenceFrom = schedule.recurrenceFrom,
)

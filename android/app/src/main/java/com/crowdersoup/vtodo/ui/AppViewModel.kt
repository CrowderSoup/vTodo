package com.crowdersoup.vtodo.ui

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.crowdersoup.vtodo.MainActivity
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.today.OpenTask
import com.crowdersoup.vtodo.today.StatusRecord
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.parseDueInput
import com.crowdersoup.vtodo.widget.refreshTodayWidget
import com.crowdersoup.vtodo.work.SyncScheduler
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate

enum class Section { Today, Open }

sealed interface Screen {
    data object List : Screen
    data object Task : Screen
    data object NewTask : Screen
}

data class TaskDraft(
    val id: Long,
    val title: String,
    val notes: String,
    val dueDate: String,
    val statusSlug: String,
)

data class NewTaskDraft(
    val title: String = "",
    val notes: String = "",
    val dueDate: String = "",
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

    val state: StateFlow<AppUiState> = combine(
        graph.sessionStore.session,
        graph.repository.observeLists(),
        combine(section, screen, draft, newTask) { section, screen, draft, newTask ->
            Chrome(section, screen, draft, newTask)
        },
        combine(refreshing, saving, message, busy) { refreshing, saving, message, busy ->
            Activity(refreshing, saving, message, busy)
        },
    ) { session, lists, chrome, activity ->
        AppUiState(
            signedIn = session != null,
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

    fun signIn(baseUrl: String, token: String) {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            message.value = null
            val result = graph.repository.signIn(baseUrl, token)
            result.onSuccess {
                SyncScheduler.onSignedIn(getApplication())
                refreshTodayWidget(getApplication())
            }.onFailure { message.value = it.message }
            refreshing.value = false
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

    fun updateNewTask(title: String? = null, notes: String? = null, dueDate: String? = null) {
        val current = newTask.value
        newTask.value = current.copy(
            title = title ?: current.title,
            notes = notes ?: current.notes,
            dueDate = dueDate ?: current.dueDate,
        )
    }

    fun openFromIntent(intent: Intent?) {
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
        if (graph.sessionStore.current() == null) return
        viewModelScope.launch {
            val task = graph.repository.findTask(id)
            if (task == null) {
                message.value = "That task isn't on this phone yet. Refresh and try again."
                return@launch
            }
            draft.value = task.toDraft()
            message.value = null
            screen.value = Screen.Task
        }
    }

    fun updateDraft(title: String? = null, notes: String? = null, dueDate: String? = null) {
        val current = draft.value ?: return
        draft.value = current.copy(
            title = title ?: current.title,
            notes = notes ?: current.notes,
            dueDate = dueDate ?: current.dueDate,
        )
    }

    fun saveNewTask() {
        if (saving.value) return
        val draft = newTask.value
        val due = parseDueInput(draft.dueDate).getOrElse {
            message.value = it.message
            return
        }
        viewModelScope.launch {
            saving.value = true
            message.value = null
            val result = graph.repository.createTask(draft.title, draft.notes, due)
            result.onSuccess {
                refreshTodayWidget(getApplication())
                section.value = if (due != null && !due.isAfter(LocalDate.now())) {
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
        val due = parseDueInput(current.dueDate).getOrElse {
            message.value = it.message
            return
        }
        viewModelScope.launch {
            saving.value = true
            message.value = null
            val result = graph.repository.saveTask(current.id, current.title, current.notes, due)
            result.onSuccess {
                refreshTodayWidget(getApplication())
                draft.value = draft.value?.copy(title = current.title.trim(), notes = current.notes.trim())
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
    statusSlug = statusSlug,
)

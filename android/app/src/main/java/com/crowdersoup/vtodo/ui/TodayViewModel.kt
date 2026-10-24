package com.crowdersoup.vtodo.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.widget.refreshTodayWidget
import com.crowdersoup.vtodo.work.SyncScheduler
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class TodayUiState(
    val signedIn: Boolean = false,
    val tasks: List<TodayTask> = emptyList(),
    val refreshing: Boolean = false,
    val message: String? = null,
    val completing: Set<Long> = emptySet(),
)

class TodayViewModel(app: Application) : AndroidViewModel(app) {
    private val graph = (app as VtodoApp).graph
    private val refreshing = MutableStateFlow(false)
    private val message = MutableStateFlow<String?>(null)
    private val completing = MutableStateFlow<Set<Long>>(emptySet())

    val state: StateFlow<TodayUiState> = combine(
        graph.sessionStore.session,
        graph.repository.observeToday(),
        refreshing,
        message,
        completing,
    ) { session, tasks, isRefreshing, note, busy ->
        TodayUiState(
            signedIn = session != null,
            tasks = tasks,
            refreshing = isRefreshing,
            message = note,
            completing = busy,
        )
    }.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        TodayUiState(signedIn = graph.sessionStore.current() != null),
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

    fun complete(taskId: Long) {
        if (taskId in completing.value) return
        viewModelScope.launch {
            completing.value = completing.value + taskId
            val result = graph.repository.complete(taskId)
            refreshTodayWidget(getApplication())
            result.onFailure { message.value = it.message ?: "Couldn't complete that task." }
            completing.value = completing.value - taskId
        }
    }

    fun signOut() {
        viewModelScope.launch {
            SyncScheduler.cancel(getApplication())
            graph.repository.signOut()
            message.value = null
            refreshTodayWidget(getApplication())
        }
    }
}

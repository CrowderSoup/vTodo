package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.crowdersoup.vtodo.R
import com.crowdersoup.vtodo.today.dueLabel
import com.crowdersoup.vtodo.today.openDateLabel
import com.crowdersoup.vtodo.today.recurrenceLabel
import java.time.LocalDate
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TaskListScreen(state: AppUiState, viewModel: AppViewModel) {
    val today = LocalDate.now()
    Scaffold(
        topBar = {
            Column {
                TopAppBar(
                    title = { Text(stringResource(R.string.app_name)) },
                    actions = {
                        if (state.refreshing) {
                            CircularProgressIndicator(
                                modifier = Modifier
                                    .padding(end = 16.dp)
                                    .size(20.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            TextButton(onClick = viewModel::refresh) {
                                Text(stringResource(R.string.refresh))
                            }
                        }
                        TextButton(onClick = viewModel::signOut) {
                            Text(stringResource(R.string.sign_out))
                        }
                    },
                )
                Row(modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp)) {
                    FilterChip(
                        selected = state.section == Section.Today,
                        onClick = { viewModel.showSection(Section.Today) },
                        label = { Text(stringResource(R.string.today)) },
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    FilterChip(
                        selected = state.section == Section.Open,
                        onClick = { viewModel.showSection(Section.Open) },
                        label = { Text(stringResource(R.string.open_tasks)) },
                    )
                }
            }
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(onClick = viewModel::startNewTask) {
                Text(stringResource(R.string.add_task))
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            state.message?.let { note ->
                Text(
                    text = note,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
            when (state.section) {
                Section.Today -> TodayList(state, today, viewModel)
                Section.Open -> OpenList(state, today, viewModel)
            }
        }
    }
}

@Composable
private fun TodayList(state: AppUiState, today: LocalDate, viewModel: AppViewModel) {
    if (state.today.isEmpty()) {
        EmptyText(stringResource(R.string.nothing_due))
    } else {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 96.dp),
        ) {
            items(state.today, key = { it.id }) { task ->
                CheckRow(
                    title = task.title,
                    subtitle = dueLabel(task, today, Locale.getDefault()),
                    overdue = task.dueDate < today,
                    statusName = task.statusName,
                    statusColor = task.statusColor,
                    tags = task.tags,
                    recurrenceDays = task.recurrenceDays,
                    enabled = task.id !in state.busy,
                    onComplete = { viewModel.complete(task.id) },
                    onOpen = { viewModel.showTask(task.id) },
                )
            }
        }
    }
}

@Composable
private fun OpenList(state: AppUiState, today: LocalDate, viewModel: AppViewModel) {
    if (state.open.isEmpty()) {
        EmptyText(stringResource(R.string.nothing_open))
    } else {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 96.dp),
        ) {
            items(state.open, key = { it.id }) { task ->
                CheckRow(
                    title = task.title,
                    subtitle = openDateLabel(task, today, Locale.getDefault()),
                    overdue = task.dueDate != null && task.dueDate < today,
                    statusName = task.statusName,
                    statusColor = task.statusColor,
                    tags = task.tags,
                    recurrenceDays = task.recurrenceDays,
                    enabled = task.id !in state.busy,
                    onComplete = { viewModel.complete(task.id) },
                    onOpen = { viewModel.showTask(task.id) },
                )
            }
        }
    }
}

@Composable
private fun EmptyText(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 24.dp),
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CheckRow(
    title: String,
    subtitle: String?,
    overdue: Boolean,
    statusName: String,
    statusColor: String,
    tags: List<String>,
    recurrenceDays: Int?,
    enabled: Boolean,
    onComplete: () -> Unit,
    onOpen: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(
            checked = false,
            onCheckedChange = { onComplete() },
            enabled = enabled,
        )
        Column(
            modifier = Modifier
                .weight(1f)
                .clickable(onClick = onOpen)
                .padding(vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(text = title, style = MaterialTheme.typography.bodyLarge)
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (statusName.isNotBlank()) {
                    StatusChip(name = statusName, colorHex = statusColor, selected = true)
                }
                tags.forEach { tag -> TagChip(tag) }
                recurrenceDays?.takeIf { it >= 1 }?.let { days -> MetaChip(recurrenceLabel(days)) }
            }
            if (!subtitle.isNullOrBlank()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (overdue) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
        }
    }
}

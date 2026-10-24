package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
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
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.dueLabel
import java.time.LocalDate
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TodayScreen(state: TodayUiState, viewModel: TodayViewModel) {
    val today = LocalDate.now()
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.today)) },
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
            if (state.tasks.isEmpty()) {
                Text(
                    text = stringResource(R.string.nothing_due),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 24.dp),
                )
            } else {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(state.tasks, key = { it.id }) { task ->
                        TaskRow(
                            task = task,
                            today = today,
                            enabled = task.id !in state.completing,
                            onComplete = { viewModel.complete(task.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TaskRow(
    task: TodayTask,
    today: LocalDate,
    enabled: Boolean,
    onComplete: () -> Unit,
) {
    val overdue = task.dueDate < today
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
        Column(verticalArrangement = Arrangement.Center) {
            Text(text = task.title, style = MaterialTheme.typography.bodyLarge)
            Text(
                text = dueLabel(task, today, Locale.getDefault()),
                style = MaterialTheme.typography.bodySmall,
                color = if (overdue) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f)
                },
            )
        }
    }
}

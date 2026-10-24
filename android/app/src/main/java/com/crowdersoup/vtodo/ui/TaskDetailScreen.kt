package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.crowdersoup.vtodo.R
import com.crowdersoup.vtodo.today.dueChipLabel
import com.crowdersoup.vtodo.today.recurrenceLabel
import java.time.LocalDate
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun TaskDetailScreen(state: AppUiState, viewModel: AppViewModel) {
    val draft = state.draft
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.task)) },
                navigationIcon = {
                    TextButton(onClick = viewModel::showList) {
                        Text(stringResource(R.string.back))
                    }
                },
                actions = {
                    if (draft != null) {
                        TextButton(onClick = viewModel::startEditing) {
                            Text(stringResource(R.string.edit))
                        }
                    }
                },
            )
        },
    ) { padding ->
        if (draft == null) {
            Text(
                text = stringResource(R.string.nothing_open),
                modifier = Modifier.padding(padding).padding(16.dp),
            )
            return@Scaffold
        }
        val today = LocalDate.now()
        val due = draft.dueDate.takeIf { it.isNotBlank() }?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            state.message?.let { note ->
                Text(text = note, color = MaterialTheme.colorScheme.error)
            }
            Text(text = draft.title, style = MaterialTheme.typography.headlineSmall)
            val repeatDays = draft.recurrenceDays.toIntOrNull()?.takeIf { it >= 1 }
            if (due != null || repeatDays != null) {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (due != null) {
                        MetaChip(
                            text = dueChipLabel(due, draft.dueTime, today, Locale.getDefault()),
                            danger = due < today,
                        )
                    }
                    if (repeatDays != null) {
                        MetaChip(text = recurrenceLabel(repeatDays))
                    }
                }
            }
            SectionLabel(stringResource(R.string.status))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                state.statuses.forEach { item ->
                    StatusChip(
                        name = item.name.ifBlank { item.slug },
                        colorHex = item.color,
                        selected = item.slug == draft.statusSlug,
                        onClick = if (draft.id in state.busy) null else ({ viewModel.moveTask(item.slug) }),
                    )
                }
            }
            if (draft.tags.isNotEmpty()) {
                SectionLabel(stringResource(R.string.tags))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    draft.tags.forEach { tag -> TagChip(tag) }
                }
            }
            SectionLabel(stringResource(R.string.notes))
            if (draft.notes.isBlank()) {
                Text(
                    text = stringResource(R.string.notes_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                NotesView(draft.notes)
            }
            RemoveTaskControl(
                enabled = draft.id !in state.busy && !state.saving,
                onRemove = viewModel::deleteTask,
            )
        }
    }
}

@Composable
internal fun RemoveTaskControl(enabled: Boolean, onRemove: () -> Unit) {
    var confirm by rememberSaveable { mutableStateOf(false) }
    TextButton(onClick = { confirm = true }, enabled = enabled) {
        Text(
            text = stringResource(R.string.remove_task),
            color = MaterialTheme.colorScheme.error,
        )
    }
    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text(stringResource(R.string.remove_task_title)) },
            text = { Text(stringResource(R.string.remove_task_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirm = false
                        onRemove()
                    },
                    enabled = enabled,
                ) {
                    Text(
                        text = stringResource(R.string.remove),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { confirm = false }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
internal fun SectionLabel(text: String) {
    Text(
        text = text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.crowdersoup.vtodo.R
import com.crowdersoup.vtodo.today.RECURRENCE_FROM_COMPLETION
import com.crowdersoup.vtodo.today.RECURRENCE_FROM_DUE_DATE
import com.crowdersoup.vtodo.today.normalizeTags
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import android.text.format.DateFormat

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun TaskEditorScreen(state: AppUiState, viewModel: AppViewModel) {
    val creating = state.screen == Screen.NewTask
    val draft = state.draft
    val title = if (creating) state.newTask.title else draft?.title.orEmpty()
    val notes = if (creating) state.newTask.notes else draft?.notes.orEmpty()
    val dueDate = if (creating) state.newTask.dueDate else draft?.dueDate.orEmpty()
    val dueTime = if (creating) state.newTask.dueTime else draft?.dueTime
    val tags = if (creating) state.newTask.tags else draft?.tags.orEmpty()
    val recurrenceDays = if (creating) state.newTask.recurrenceDays else draft?.recurrenceDays.orEmpty()
    val recurrenceFrom = if (creating) {
        state.newTask.recurrenceFrom
    } else {
        draft?.recurrenceFrom ?: RECURRENCE_FROM_COMPLETION
    }
    var pendingTag by rememberSaveable { mutableStateOf("") }
    val knownTags = normalizeTags(state.today.flatMap { it.tags } + state.open.flatMap { it.tags })
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(stringResource(if (creating) R.string.new_task else R.string.edit_task))
                },
                navigationIcon = {
                    TextButton(onClick = viewModel::backFromEditor) {
                        Text(stringResource(R.string.back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            state.message?.let { note ->
                Text(text = note, color = MaterialTheme.colorScheme.error)
            }
            OutlinedTextField(
                value = title,
                onValueChange = { value ->
                    if (creating) viewModel.updateNewTask(title = value) else viewModel.updateDraft(title = value)
                },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.title)) },
                singleLine = true,
            )
            DueDateField(
                value = dueDate,
                onChange = { value ->
                    if (creating) viewModel.updateNewTask(dueDate = value) else viewModel.updateDraft(dueDate = value)
                },
            )
            if (dueDate.isNotBlank()) {
                DueTimeField(
                    value = dueTime,
                    onChange = { time ->
                        if (creating) {
                            viewModel.updateNewTask(dueTime = time, clearDueTime = time == null)
                        } else {
                            viewModel.updateDraft(dueTime = time, clearDueTime = time == null)
                        }
                    },
                )
            }
            RecurrenceFields(
                days = recurrenceDays,
                from = recurrenceFrom,
                onDays = { value ->
                    if (creating) viewModel.updateNewTask(recurrenceDays = value) else viewModel.updateDraft(recurrenceDays = value)
                },
                onFrom = { value ->
                    if (creating) viewModel.updateNewTask(recurrenceFrom = value) else viewModel.updateDraft(recurrenceFrom = value)
                },
            )
            if (!creating && draft != null) {
                SectionLabel(stringResource(R.string.status))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    state.statuses.forEach { status ->
                        StatusChip(
                            name = status.name.ifBlank { status.slug },
                            colorHex = status.color,
                            selected = status.slug == draft.statusSlug,
                            onClick = if (draft.id in state.busy) null else ({ viewModel.moveTask(status.slug) }),
                        )
                    }
                }
            }
            TagEditor(
                tags = tags,
                pending = pendingTag,
                known = knownTags,
                onPending = { pendingTag = it },
                onTags = { next ->
                    if (creating) viewModel.updateNewTask(tags = next) else viewModel.updateDraft(tags = next)
                },
            )
            NotesEditor(
                notes = notes,
                onChange = { value ->
                    if (creating) viewModel.updateNewTask(notes = value) else viewModel.updateDraft(notes = value)
                },
            )
            Button(
                onClick = {
                    val next = normalizeTags(tags + pendingTag.split(','))
                    pendingTag = ""
                    if (creating) {
                        viewModel.updateNewTask(tags = next)
                        viewModel.saveNewTask()
                    } else {
                        viewModel.updateDraft(tags = next)
                        viewModel.saveTask()
                    }
                },
                enabled = !state.saving,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.saving) {
                    CircularProgressIndicator(modifier = Modifier.height(18.dp), strokeWidth = 2.dp)
                } else {
                    Text(stringResource(R.string.save))
                }
            }
            if (!creating) {
                RemoveTaskControl(enabled = !state.saving, onRemove = viewModel::deleteTask)
            }
            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TagEditor(
    tags: List<String>,
    pending: String,
    known: List<String>,
    onPending: (String) -> Unit,
    onTags: (List<String>) -> Unit,
) {
    fun commit(raw: String) {
        val next = normalizeTags(tags + raw.split(','))
        if (next != tags) onTags(next)
        onPending("")
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionLabel(stringResource(R.string.tags))
        if (tags.isNotEmpty()) {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                tags.forEach { tag ->
                    TagChip(text = tag, onClick = { onTags(tags.filterNot { it == tag }) })
                }
            }
            Text(
                text = stringResource(R.string.remove_tag_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        OutlinedTextField(
            value = pending,
            onValueChange = { value ->
                if (value.endsWith(",") || value.endsWith("\n")) commit(value.dropLast(1)) else onPending(value)
            },
            modifier = Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.add_tag)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { commit(pending) }),
        )
        val suggestions = known.filter { it !in tags }
        if (suggestions.isNotEmpty()) {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                suggestions.forEach { tag ->
                    SuggestionChip(onClick = { onTags(normalizeTags(tags + tag)) }, label = { Text(tag) })
                }
            }
        }
    }
}

@Composable
private fun NotesEditor(notes: String, onChange: (String) -> Unit) {
    var preview by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = !preview,
                onClick = { preview = false },
                label = { Text(stringResource(R.string.write)) },
            )
            FilterChip(
                selected = preview,
                onClick = { preview = true },
                label = { Text(stringResource(R.string.preview)) },
            )
        }
        if (preview) {
            if (notes.isBlank()) {
                Text(
                    text = stringResource(R.string.notes_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                NotesView(notes)
            }
        } else {
            OutlinedTextField(
                value = notes,
                onValueChange = onChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.notes)) },
                placeholder = { Text(stringResource(R.string.notes_hint)) },
                minLines = 8,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DueTimeField(value: LocalTime?, onChange: (LocalTime?) -> Unit) {
    var open by rememberSaveable { mutableStateOf(false) }
    val label = value?.format(DateTimeFormatter.ofPattern("h:mm a", Locale.getDefault()))
        ?: stringResource(R.string.no_time)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        TextButton(onClick = { open = true }) {
            Text(stringResource(R.string.due_time) + ": " + label)
        }
        if (value != null) {
            TextButton(onClick = { onChange(null) }) {
                Text(stringResource(R.string.clear_time))
            }
        }
    }
    if (open) {
        val pickerState = rememberTimePickerState(
            initialHour = value?.hour ?: 9,
            initialMinute = value?.minute ?: 0,
            is24Hour = DateFormat.is24HourFormat(LocalContext.current),
        )
        AlertDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        onChange(LocalTime.of(pickerState.hour, pickerState.minute))
                        open = false
                    },
                ) { Text(stringResource(R.string.save)) }
            },
            dismissButton = {
                TextButton(onClick = { open = false }) { Text(stringResource(R.string.back)) }
            },
            text = { TimePicker(state = pickerState) },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RecurrenceFields(
    days: String,
    from: String,
    onDays: (String) -> Unit,
    onFrom: (String) -> Unit,
) {
    OutlinedTextField(
        value = days,
        onValueChange = { raw -> onDays(raw.filter { it.isDigit() }.take(5)) },
        modifier = Modifier.fillMaxWidth(),
        label = { Text(stringResource(R.string.repeat_every)) },
        placeholder = { Text(stringResource(R.string.repeat_every_hint)) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    )
    SectionLabel(stringResource(R.string.repeat_from))
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        FilterChip(
            selected = from != RECURRENCE_FROM_DUE_DATE,
            onClick = { onFrom(RECURRENCE_FROM_COMPLETION) },
            label = { Text(stringResource(R.string.repeat_from_completion)) },
        )
        FilterChip(
            selected = from == RECURRENCE_FROM_DUE_DATE,
            onClick = { onFrom(RECURRENCE_FROM_DUE_DATE) },
            label = { Text(stringResource(R.string.repeat_from_due)) },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DueDateField(value: String, onChange: (String) -> Unit) {
    var open by rememberSaveable { mutableStateOf(false) }
    val parsed = value.takeIf { it.isNotBlank() }?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
    val label = parsed?.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(Locale.getDefault()))
        ?: stringResource(R.string.no_date)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        TextButton(onClick = { open = true }) {
            Text(stringResource(R.string.due_date) + ": " + label)
        }
        if (value.isNotBlank()) {
            TextButton(onClick = { onChange("") }) {
                Text(stringResource(R.string.clear_date))
            }
        }
    }
    if (open) {
        val pickerState = rememberDatePickerState(
            initialSelectedDateMillis = parsed?.atStartOfDay(ZoneOffset.UTC)?.toInstant()?.toEpochMilli(),
        )
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        pickerState.selectedDateMillis?.let { millis ->
                            val date = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                            onChange(date.toString())
                        }
                        open = false
                    },
                ) { Text(stringResource(R.string.save)) }
            },
            dismissButton = {
                TextButton(onClick = { open = false }) { Text(stringResource(R.string.back)) }
            },
        ) {
            DatePicker(state = pickerState)
        }
    }
}


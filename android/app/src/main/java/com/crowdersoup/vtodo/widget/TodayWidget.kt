package com.crowdersoup.vtodo.widget

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.LocalContext
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.clickable
import androidx.glance.appwidget.CheckBox
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.appWidgetBackground
import androidx.glance.appwidget.lazy.LazyColumn
import androidx.glance.appwidget.lazy.items
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.color.ColorProvider
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import com.crowdersoup.vtodo.MainActivity
import com.crowdersoup.vtodo.R
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.brand.Brand
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.dueLabel
import java.time.LocalDate
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

val TaskIdKey = ActionParameters.Key<Long>("taskId")

private val widgetBackground = ColorProvider(Color(Brand.BG), Color(Brand.DARK_BG))
private val widgetText = ColorProvider(Color(Brand.TEXT), Color(Brand.DARK_TEXT))
private val widgetSoft = ColorProvider(Color(Brand.TEXT_SOFT), Color(Brand.DARK_TEXT_SOFT))
private val widgetAccent = ColorProvider(Color(Brand.ACCENT), Color(Brand.DARK_ACCENT))
private val widgetDanger = ColorProvider(Color(Brand.DANGER), Color(Brand.DARK_DANGER))

class TodayWidget : GlanceAppWidget() {
    override val sizeMode: SizeMode = SizeMode.Exact

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val app = context.applicationContext as? VtodoApp
        if (app == null) {
            provideContent { TodayWidgetBody(WidgetModel.SignedOut) }
            return
        }
        // updateAll does not rerun provideGlance while this session is alive.
        // The list has to be collected here, or checking a task off in the app
        // recomposes the snapshot from when the session started.
        val graph = app.graph
        val initial = if (graph.sessionStore.current() != null) {
            graph.repository.todaySnapshot()
        } else {
            emptyList()
        }
        provideContent {
            val session by graph.sessionStore.session.collectAsState()
            val tasks by graph.repository.observeToday().collectAsState(initial)
            val model = if (session == null) {
                WidgetModel.SignedOut
            } else {
                WidgetModel.Ready(LocalDate.now(), tasks)
            }
            TodayWidgetBody(model)
        }
    }
}

private sealed interface WidgetModel {
    data object SignedOut : WidgetModel
    data class Ready(val today: LocalDate, val tasks: List<TodayTask>) : WidgetModel
}

@androidx.compose.runtime.Composable
private fun TodayWidgetBody(model: WidgetModel) {
    val context = LocalContext.current
    LazyColumn(
        modifier = GlanceModifier
            .fillMaxSize()
            .appWidgetBackground()
            .background(widgetBackground),
    ) {
        item {
            Text(
                text = context.getString(R.string.today),
                modifier = GlanceModifier
                    .fillMaxWidth()
                    .padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp)
                    .clickable(actionStartActivity(openAppIntent(context))),
                style = TextStyle(
                    color = widgetText,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                ),
            )
        }
        when (model) {
            WidgetModel.SignedOut -> item {
                Text(
                    text = context.getString(R.string.widget_sign_in),
                    modifier = GlanceModifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp)
                        .clickable(actionStartActivity(openAppIntent(context))),
                    style = TextStyle(color = widgetAccent, fontSize = 14.sp),
                )
            }
            is WidgetModel.Ready -> {
                if (model.tasks.isEmpty()) {
                    item {
                        Text(
                            text = context.getString(R.string.widget_empty),
                            modifier = GlanceModifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = 4.dp)
                                .clickable(actionStartActivity(openAppIntent(context))),
                            style = TextStyle(color = widgetSoft, fontSize = 14.sp),
                        )
                    }
                } else {
                    items(model.tasks, itemId = { it.id }) { task ->
                        TaskRow(task, model.today)
                    }
                    item { Spacer(modifier = GlanceModifier.height(12.dp)) }
                }
            }
        }
    }
}

private fun openAppIntent(context: Context, taskId: Long? = null): Intent {
    return Intent(context, MainActivity::class.java).apply {
        action = MainActivity.ACTION_OPEN
        if (taskId != null) putExtra(MainActivity.EXTRA_TASK_ID, taskId)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    }
}

@androidx.compose.runtime.Composable
private fun TaskRow(task: TodayTask, today: LocalDate) {
    val context = LocalContext.current
    val labelColor = if (task.dueDate < today) widgetDanger else widgetSoft
    Row(
        modifier = GlanceModifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CheckBox(
            checked = false,
            onCheckedChange = actionRunCallback<CompleteTaskAction>(
                actionParametersOf(TaskIdKey to task.id),
            ),
        )
        Column(
            modifier = GlanceModifier
                .defaultWeight()
                .clickable(actionStartActivity(openAppIntent(context, task.id))),
        ) {
            Text(
                text = task.title,
                maxLines = 2,
                style = TextStyle(color = widgetText, fontSize = 14.sp),
            )
            Text(
                text = dueLabel(task, today, Locale.getDefault()),
                maxLines = 1,
                style = TextStyle(color = labelColor, fontSize = 12.sp),
            )
            val meta = listOfNotNull(
                task.statusName.takeIf { it.isNotBlank() },
                task.tags.takeIf { it.isNotEmpty() }?.joinToString(", "),
            ).joinToString(" · ")
            if (meta.isNotEmpty()) {
                Text(
                    text = meta,
                    maxLines = 1,
                    style = TextStyle(color = widgetSoft, fontSize = 12.sp),
                )
            }
        }
    }
}

class CompleteTaskAction : ActionCallback {
    override suspend fun onAction(
        context: Context,
        glanceId: GlanceId,
        parameters: ActionParameters,
    ) {
        val taskId = parameters[TaskIdKey] ?: return
        val app = context.applicationContext as? VtodoApp ?: return
        app.graph.repository.complete(taskId)
        refreshTodayWidget(context)
    }
}

class TodayWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = TodayWidget()
}

private val widgetUpdate = Mutex()

suspend fun refreshTodayWidget(context: Context) {
    withContext(Dispatchers.Main.immediate) {
        widgetUpdate.withLock {
            TodayWidget().updateAll(context)
        }
    }
}

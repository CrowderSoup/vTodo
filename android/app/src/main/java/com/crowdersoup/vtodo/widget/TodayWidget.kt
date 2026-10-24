package com.crowdersoup.vtodo.widget

import android.content.Context
import android.content.Intent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.LocalContext
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.clickable
import androidx.glance.appwidget.CheckBox
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.appWidgetBackground
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
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
import androidx.glance.unit.ColorProvider
import com.crowdersoup.vtodo.MainActivity
import com.crowdersoup.vtodo.R
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.today.TodayTask
import com.crowdersoup.vtodo.today.dueLabel
import java.time.LocalDate
import java.util.Locale

private const val MAX_ROWS = 8

val TaskIdKey = ActionParameters.Key<Long>("taskId")

class TodayWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val model = loadModel(context)
        provideContent {
            GlanceTheme {
                TodayWidgetBody(model)
            }
        }
    }
}

private suspend fun loadModel(context: Context): WidgetModel {
    val app = context.applicationContext as? VtodoApp ?: return WidgetModel.SignedOut
    if (app.graph.sessionStore.current() == null) return WidgetModel.SignedOut
    val today = LocalDate.now()
    return WidgetModel.Ready(today, app.graph.repository.todaySnapshot(today))
}

private sealed interface WidgetModel {
    data object SignedOut : WidgetModel
    data class Ready(val today: LocalDate, val tasks: List<TodayTask>) : WidgetModel
}

@androidx.compose.runtime.Composable
private fun TodayWidgetBody(model: WidgetModel) {
    val context = LocalContext.current
    val openApp = actionStartActivity(Intent(context, MainActivity::class.java))
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .appWidgetBackground()
            .background(GlanceTheme.colors.widgetBackground)
            .padding(16.dp),
    ) {
        Text(
            text = context.getString(R.string.today),
            modifier = GlanceModifier.clickable(openApp),
            style = TextStyle(
                color = GlanceTheme.colors.onSurface,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
            ),
        )
        Spacer(modifier = GlanceModifier.height(8.dp))
        when (model) {
            WidgetModel.SignedOut -> {
                Text(
                    text = context.getString(R.string.widget_sign_in),
                    modifier = GlanceModifier.clickable(openApp),
                    style = TextStyle(color = GlanceTheme.colors.primary, fontSize = 14.sp),
                )
            }
            is WidgetModel.Ready -> {
                if (model.tasks.isEmpty()) {
                    Text(
                        text = context.getString(R.string.widget_empty),
                        modifier = GlanceModifier.clickable(openApp),
                        style = TextStyle(color = GlanceTheme.colors.onSurfaceVariant, fontSize = 14.sp),
                    )
                } else {
                    model.tasks.take(MAX_ROWS).forEach { task ->
                        TaskRow(task, model.today)
                    }
                    val extra = model.tasks.size - MAX_ROWS
                    if (extra > 0) {
                        Spacer(modifier = GlanceModifier.height(4.dp))
                        Text(
                            text = context.getString(R.string.widget_more, extra),
                            style = TextStyle(color = GlanceTheme.colors.onSurfaceVariant, fontSize = 12.sp),
                        )
                    }
                }
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun TaskRow(task: TodayTask, today: LocalDate) {
    val context = LocalContext.current
    val overdue = task.dueDate < today
    val labelColor = if (overdue) {
        ColorProvider(Color(0xFFBB4D3E))
    } else {
        GlanceTheme.colors.onSurfaceVariant
    }
    Row(
        modifier = GlanceModifier.fillMaxWidth().padding(vertical = 2.dp),
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
                .clickable(actionStartActivity(Intent(context, MainActivity::class.java))),
        ) {
            Text(
                text = task.title,
                maxLines = 2,
                style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 14.sp),
            )
            Text(
                text = dueLabel(task, today, Locale.getDefault()),
                maxLines = 1,
                style = TextStyle(color = labelColor, fontSize = 12.sp),
            )
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

suspend fun refreshTodayWidget(context: Context) {
    TodayWidget().updateAll(context)
}

package com.crowdersoup.vtodo.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.widget.refreshTodayWidget

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val repository = (applicationContext as VtodoApp).graph.repository
        val outcome = repository.sync()
        refreshTodayWidget(applicationContext)
        return workerResult(outcome)
    }
}

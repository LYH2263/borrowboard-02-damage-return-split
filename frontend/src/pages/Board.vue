<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <div v-for="i in board.available" :key="i.id" class="item">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.id].borrower" placeholder="借用人" />
        <input v-model="forms[i.id].due_date" placeholder="应还日 YYYY-MM-DD" />
        <button @click="lend(i.id)">借出通过</button>
      </div>
      <h2>待解锁（破损）</h2>
      <div v-for="i in board.held" :key="'h' + i.id" class="item held">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }} · 破损待解锁，解锁后才可借</div>
        <button @click="unlock(i.id)">解锁回可借栏</button>
      </div>
      <div v-if="!board.held.length" class="muted">无</div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id" class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <template v-if="rets[l.id]">
          <textarea v-model="rets[l.id].note" placeholder="破损说明（可空）" rows="2"></textarea>
          <div v-if="rets[l.id].preview" class="muted">
            确认后：{{ rets[l.id].preview.damage ? '停物主栏待解锁' : '回可借栏' }}
          </div>
          <button @click="preview(l.id)">预览</button>
          <button @click="confirm(l.id)">确认归还</button>
          <button @click="rets[l.id] = null">取消</button>
        </template>
        <button v-else @click="rets[l.id] = { note: '', preview: null }">归还</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { inject, reactive, watch } from 'vue'
import { api } from '../api'
const board = inject('board')
const reload = inject('reloadBoard')
const forms = reactive({})
const rets = reactive({})
watch(board, (b) => {
  for (const i of (b.available || [])) {
    if (!forms[i.id]) forms[i.id] = { borrower: '邻居', due_date: '2026-12-31' }
  }
}, { immediate: true, deep: true })
async function lend(id) {
  await api('/items/' + id + '/lend', { method: 'POST', body: JSON.stringify(forms[id]) })
  await reload()
}
async function preview(id) {
  rets[id].preview = await api('/loans/' + id + '/return/preview', {
    method: 'POST', body: JSON.stringify({ note: rets[id].note }),
  })
}
async function confirm(id) {
  await api('/loans/' + id + '/return', {
    method: 'POST', body: JSON.stringify({ note: rets[id].note }),
  })
  delete rets[id]
  await reload()
}
async function unlock(id) {
  await api('/items/' + id + '/unlock', { method: 'POST', body: '{}' })
  await reload()
}
</script>

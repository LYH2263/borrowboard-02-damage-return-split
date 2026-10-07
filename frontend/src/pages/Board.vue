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
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id" class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <template v-if="rets[l.id]">
          <textarea v-model="rets[l.id].note" rows="2" placeholder="破损说明（可空；填写则确认后停物主栏待解锁）"></textarea>
          <div v-if="rets[l.id].preview" class="muted">
            确认后：{{ rets[l.id].preview.landing_column === 'owner' ? '停物主栏，待解锁才可借' : '直接回可借栏' }}
          </div>
          <div v-if="rets[l.id].error" class="err">归还失败：{{ rets[l.id].error }}</div>
          <button @click="previewRet(l.id)">预览</button>
          <button @click="confirmRet(l.id)">确认归还</button>
        </template>
        <button v-else @click="openRet(l.id)">归还</button>
      </div>
    </section>
    <section class="pane">
      <h2>物主栏 · 待解锁</h2>
      <div v-if="!(board.owner_hold || []).length" class="muted">无待解锁物</div>
      <div v-for="i in board.owner_hold" :key="i.id" class="item held">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <div class="muted">破损：{{ i.damage_note }}</div>
        <button @click="unlock(i.id)">解锁回可借栏</button>
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
function openRet(id) {
  rets[id] = { note: '', preview: null, error: '' }
}
async function previewRet(id) {
  try {
    rets[id].preview = await api('/loans/' + id + '/return/preview', {
      method: 'POST', body: JSON.stringify({ note: rets[id].note }),
    })
    rets[id].error = ''
  } catch (e) { rets[id].error = e.message }
}
async function confirmRet(id) {
  try {
    await api('/loans/' + id + '/return/confirm', {
      method: 'POST', body: JSON.stringify({ note: rets[id].note }),
    })
    delete rets[id]
  } catch (e) {
    rets[id].error = e.message
  }
  await reload()
}
async function unlock(id) {
  await api('/items/' + id + '/unlock', { method: 'POST', body: '{}' })
  await reload()
}
</script>

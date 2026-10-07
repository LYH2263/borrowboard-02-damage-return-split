<template>
  <div style="padding:16px">
    <h1>物主一览</h1>
    <div v-for="i in rows" :key="i.id" class="item" :class="{ held: i.status === 'damaged_hold' }">
      {{ i.owner || '（空）' }} · {{ i.title }} · {{ label(i.status) }}
      <button v-if="i.status === 'damaged_hold'" @click="unlock(i.id)">解锁回可借栏</button>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const LABELS = { available: '可借', on_loan: '在借', damaged_hold: '破损待解锁' }
const label = (s) => LABELS[s] || s
async function load() { rows.value = await api('/items') }
async function unlock(id) {
  await api('/items/' + id + '/unlock', { method: 'POST', body: '{}' })
  await load()
}
onMounted(load)
</script>

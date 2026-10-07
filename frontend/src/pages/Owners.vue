<template>
  <div style="padding:16px">
    <h1>物主一览</h1>
    <div v-for="i in rows" :key="i.id" class="item">{{ i.owner || '（空）' }} · {{ i.title }} · {{ label(i.status) }}</div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const LABELS = { available: '可借', on_loan: '在借', owner_hold: '待解锁' }
const label = (s) => LABELS[s] || s
onMounted(async () => { rows.value = await api('/items') })
</script>

<template>
  <div style="padding:16px">
    <h1>借还记录</h1>
    <h3>逾期</h3>
    <div v-for="l in data.overdue" :key="'o'+l.id" class="item overdue">{{ l.title }} · {{ l.borrower }}</div>
    <h3>在借</h3>
    <div v-for="l in data.active" :key="'a'+l.id" class="item">{{ l.title }} · {{ l.borrower }}</div>
    <h3>已还</h3>
    <div v-for="l in data.returned" :key="'r'+l.id" class="item">
      {{ l.title }} · {{ l.borrower }}
      <div v-if="l.damage_note" class="muted">
        破损：{{ l.damage_note }}<template v-if="l.damage_unlocked_at"> · 已解锁回可借</template><template v-else> · 待解锁</template>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const data = ref({ active: [], overdue: [], returned: [] })
onMounted(async () => { data.value = await api('/loans') })
</script>

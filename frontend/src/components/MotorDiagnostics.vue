<template>
  <div class="glass p-6 rounded-3xl h-1/2">
    <div class="flex justify-between items-end mb-6">
      <h3 class="text-[10px] font-ui text-slate-500 uppercase tracking-widest">Motor Diagnostics</h3>
      <div class="text-[10px] font-mono text-blue-400">DIFF_RATIO: 1.0</div>
    </div>
    <div class="space-y-8">
      <div v-for="(motor, index) in motors" :key="index">
        <div class="flex justify-between items-center mb-2">
          <span class="text-xs font-bold text-slate-400">{{ motor.label }}</span>
          <span class="font-mono text-xs text-white">{{ motor.rpm }} RPM</span>
        </div>
        <div class="relative h-4 bg-slate-900 rounded-full overflow-hidden border border-slate-700">
          <div 
            class="h-full bg-gradient-to-r from-blue-600 to-cyan-400 transition-all duration-75"
            :style="{ width: motor.power + '%' }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps(['telemetry']);

const motors = computed(() => [
  { label: 'Left (A)', rpm: props.telemetry.rpm_l, power: Math.abs(props.telemetry.rpm_l / 2.5) },
  { label: 'Right (B)', rpm: props.telemetry.rpm_r, power: Math.abs(props.telemetry.rpm_r / 2.5) }
]);
</script>
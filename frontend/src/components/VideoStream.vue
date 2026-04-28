<template>
  <div class="relative rounded-xl overflow-hidden bg-black aspect-video border border-slate-700">
    <img :src="videoUrl" class="w-full h-full object-contain" alt="Robot Feed" />
    <div class="absolute top-2 left-2 px-2 py-1 bg-black/50 text-[10px] rounded">
      LIVE: {{ stream_name }}
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  stream_name: { type: String, default: 'raw' }
});

// Construct URL dynamically based on backend address
const videoUrl = computed(() => `http://192.168.1.100:8000/video/${props.stream_name}`);
</script>
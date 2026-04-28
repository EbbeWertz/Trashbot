<template>
	<div
		class="relative rounded-xl overflow-hidden bg-black border border-slate-700">
		<!-- {{ fullVideoUrl }}
        {{ video_url }} -->
		<div class="max-w-md mx-auto h-full">
			<img
				:src="`${video_url}?view=${stream_name}`"
				class="w-full h-full object-contain"
				alt="Robot Feed" />
		</div>
		<div
			class="absolute top-2 left-2 px-2 py-1 bg-black/50 text-[10px] rounded">
			LIVE: {{ stream_name }}
		</div>
	</div>
</template>

<script setup>
// import { computed } from 'vue';
import { video_url } from "../services/robotService";

// const fullVideoUrl = `${video_url}?view=${stream_name}`

const props = defineProps({
	stream_name: { type: String, default: "raw" },
});

// const fullVideoUrl = computed(() => `${video_url}?view=${stream_name}`);
</script>

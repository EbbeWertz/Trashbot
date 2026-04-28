import { createRouter, createWebHistory } from 'vue-router';
import ManualControlView from '../views/ManualControlView.vue';
import CatchView from '../views/CatchView.vue';
import FollowView from '../views/FollowView.vue';
import ConfigView from '../views/ConfigView.vue';

const routes = [
  { path: '/', component: ManualControlView },
  { path: '/follow', component: FollowView },
  { path: '/catch', component: CatchView },
  { path: '/config', component: ConfigView },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
<script setup lang="ts">
defineEmits<{ start: [] }>()
const features = [
  ['01', '多城顺序', '按你设定的访问顺序安排每座城市，不擅自改写路线。'],
  ['02', '事实数据', '景点、天气与酒店信息分层呈现，缺失数据会明确提示。'],
  ['03', '预算参考', '汇总住宿、餐饮、市内与城际交通的估算，拒绝伪装实时价格。'],
  ['04', '随时调整', '城市、日期、节奏和偏好均由你决定，再生成可执行的每日安排。'],
]
</script>

<template>
  <main class="welcome-page">
    <nav class="welcome-nav"><a class="brand" href="#" @click.prevent><i>✦</i> 行知</a><span>CN TRAVEL · PLANNER</span><button type="button" @click="$emit('start')">开始规划 →</button></nav>
    <section class="welcome-hero">
      <div class="welcome-copy"><p class="kicker">YOUR NEXT JOURNEY</p><h1>把旅行的期待，<em>变成一份真的能出发的日程。</em></h1><p>从城市顺序到每日节奏，行知只依据可查询的旅行资料生成建议，并把不确定的信息清楚告诉你。</p><button class="welcome-cta" type="button" @click="$emit('start')">开始规划我的路线 <b>→</b></button></div>
      <div class="route-art" aria-label="城市路线示意图" role="img"><span class="route-dot dot-one">起</span><span class="route-dot dot-two">途</span><span class="route-dot dot-three">抵</span><i class="route-line line-one"></i><i class="route-line line-two"></i><div class="route-card card-one">城市与日期</div><div class="route-card card-two">你的每日行程</div></div>
    </section>
    <section class="feature-section"><p class="kicker">HOW IT HELPS</p><h2>旅行规划，仍由你掌舵。</h2><div class="feature-grid"><article v-for="feature in features" :key="feature[0]"><span>{{ feature[0] }}</span><h3>{{ feature[1] }}</h3><p>{{ feature[2] }}</p></article></div></section>
    <footer>行知 · 国内多城市旅行助手 <span>不提供票务、库存或预订服务</span></footer>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const city = ref('')
const docId = ref('')
const contractText = ref('')

const uploading = ref(false)
const reviewing = ref(false)

const overallScore = ref(null)
const clauses = ref([])
const selectedClauseId = ref('')
const uploadedFileName = ref('')
const uploadedFile = ref(null)
const extracting = ref(false)

const qaQuestion = ref('')
const qaAnswer = ref('')

// 保存到本地存储
function saveToStorage() {
  localStorage.setItem('contractReviewData', JSON.stringify({
    city: city.value,
    docId: docId.value,
    contractText: contractText.value,
    overallScore: overallScore.value,
    clauses: clauses.value,
    selectedClauseId: selectedClauseId.value,
    uploadedFileName: uploadedFileName.value,
    qaAnswer: qaAnswer.value,
  }))
}

// 从本地存储恢复
function loadFromStorage() {
  const saved = localStorage.getItem('contractReviewData')
  if (saved) {
    try {
      const data = JSON.parse(saved)
      city.value = data.city || ''
      docId.value = data.docId || ''
      contractText.value = data.contractText || ''
      overallScore.value = data.overallScore || null
      clauses.value = data.clauses || []
      selectedClauseId.value = data.selectedClauseId || ''
      uploadedFileName.value = data.uploadedFileName || ''
      qaAnswer.value = data.qaAnswer || ''
    } catch (e) {
      console.error('Failed to load from storage:', e)
    }
  }
}

// 清除本地存储
function clearStorage() {
  localStorage.removeItem('contractReviewData')
}

// 监听数据变化自动保存
watch([city, docId, contractText, overallScore, clauses, selectedClauseId, uploadedFileName, qaAnswer], () => {
  saveToStorage()
}, { deep: true })

// 组件挂载时恢复数据
onMounted(() => {
  loadFromStorage()
})
const sampleQuestions = [
  '押金条款有什么风险？',
  '解约条件怎么写更合理？',
  '维修责任如何划分？',
  '违约金比例多少合适？',
]
let es = null
let reviewAbort = null

const selectedClause = computed(() => clauses.value.find(c => c.clause_id === selectedClauseId.value) || null)

function riskBadgeClass(level) {
  if (level === 'high') return 'bg-red-100 text-red-700 border border-red-200'
  if (level === 'medium') return 'bg-yellow-100 text-yellow-700 border border-yellow-200'
  return 'bg-green-100 text-green-700 border border-green-200'
}

function uploadFile(file) {
  uploadedFile.value = file
  uploadedFileName.value = file.name
  contractText.value = ''
  docId.value = ''
  overallScore.value = null
  clauses.value = []
  selectedClauseId.value = ''
  qaAnswer.value = ''
}

async function extractText() {
  if (!uploadedFile.value) return
  extracting.value = true
  try {
    const fd = new FormData()
    fd.append('file', uploadedFile.value)
    const res = await fetch('/api/extract', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    docId.value = data.doc_id
    contractText.value = data.text
  } finally {
    extracting.value = false
  }
}

function clearAll() {
  contractText.value = ''
  docId.value = ''
  uploadedFileName.value = ''
  uploadedFile.value = null
  overallScore.value = null
  clauses.value = []
  selectedClauseId.value = ''
  qaAnswer.value = ''
  clearStorage()
}

async function review() {
  reviewing.value = true
  clauses.value = []
  overallScore.value = null
  selectedClauseId.value = ''
  reviewAbort = new AbortController()
  try {
    const res = await fetch('/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_id: docId.value || 'local', text: contractText.value, city: city.value || null }),
      signal: reviewAbort.signal,
    })
    if (!res.ok) throw new Error(await res.text())
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const dataStr = line.slice(5).trim()
        if (dataStr === '[DONE]') continue
        try {
          const obj = JSON.parse(dataStr)
          if (obj.type === 'clause' && obj.clause) {
            clauses.value.push(obj.clause)
            if (!selectedClauseId.value) selectedClauseId.value = obj.clause.clause_id
          } else if (obj.type === 'done') {
            overallScore.value = obj.overall_risk_score ?? null
          }
        } catch {
          // ignore parse errors
        }
      }
    }
  } finally {
    reviewing.value = false
  }
}

function stopStream() {
  if (es) {
    es.close()
    es = null
  }
  if (reviewAbort) {
    reviewAbort.abort()
    reviewAbort = null
  }
}

async function ask() {
  stopStream()
  qaAnswer.value = ''
  const url =
    `/api/qa/stream?doc_id=${encodeURIComponent(docId.value || 'local')}` +
    `&question=${encodeURIComponent(qaQuestion.value)}` +
    (city.value ? `&city=${encodeURIComponent(city.value)}` : '')

  es = new EventSource(url)
  es.onmessage = (ev) => {
    if (ev.data === '[DONE]') {
      stopStream()
      return
    }
    try {
      const obj = JSON.parse(ev.data)
      qaAnswer.value += obj.delta || ''
    } catch {
      qaAnswer.value += ev.data
    }
  }
  es.onerror = () => {
    qaAnswer.value += '\n\n（连接中断）'
    stopStream()
  }
}

onBeforeUnmount(() => stopStream())
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="border-b border-gray-200/60 bg-white/80 backdrop-blur-xl shadow-sm sticky top-0 z-10">
      <div class="mx-auto max-w-8xl px-6 py-4 flex items-center justify-between gap-6">
        <div class="flex items-center gap-3">
          <div class="w-11 h-11 rounded-2xl bg-blue-500 flex items-center justify-center shadow-lg shadow-blue-500/25">
            <span class="text-xl">📋</span>
          </div>
          <div>
            <div class="text-xl font-semibold tracking-tight text-gray-900">租赁租房合同审核（DEMO）</div>
            <div class="text-xs text-gray-500 mt-0.5">智能 AI 驱动的合同风险审查系统</div>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <input
            v-model="city"
            class="w-44 rounded-2xl border border-gray-200 bg-gray-50/80 backdrop-blur-sm px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:bg-white transition-all text-gray-900 placeholder-gray-400"
            placeholder="城市（可选）"
          />
          <button
            class="rounded-2xl bg-blue-500 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-blue-500/20 active:scale-95"
            :disabled="reviewing || !contractText.trim()"
            @click="review"
          >
            <span class="flex items-center gap-2">
              <span v-if="reviewing" class="animate-spin">⏳</span>
              <span>{{ reviewing ? '审查中…' : '开始审查' }}</span>
            </span>
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-8xl w-full flex-1 px-4 py-4">
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 h-full">
        <!-- Left: contract -->
        <section class="rounded-3xl border border-gray-200/60 bg-white/80 backdrop-blur-xl overflow-hidden flex flex-col min-h-[540px] shadow-lg shadow-gray-200/50">
          <div class="p-5 border-b border-gray-200/60 flex items-center justify-between gap-3 bg-gray-50/50">
            <div class="flex items-center gap-2">
              <span class="text-lg">📄</span>
              <div class="text-sm font-semibold text-gray-900">合同原文</div>
            </div>
            <div class="flex items-center gap-2">
              <label class="inline-flex items-center gap-2 text-xs text-gray-600">
                <input
                  type="file"
                  class="block w-[180px] text-xs text-gray-600 file:mr-3 file:rounded-2xl file:border-0 file:bg-gray-100 file:px-4 file:py-2.5 file:text-xs file:font-medium file:text-gray-700 hover:file:bg-gray-200 transition-all"
                  :disabled="extracting"
                  @change="(e) => e.target.files?.[0] && uploadFile(e.target.files[0])"
                />
                <span v-if="extracting" class="text-blue-600 flex items-center gap-1"><span class="animate-spin">⏳</span>解析中…</span>
                <span v-else-if="uploadedFileName" class="text-gray-500 truncate max-w-[100px] flex items-center gap-1">📎 {{ uploadedFileName }}</span>
              </label>
              <button
                v-if="uploadedFile"
                class="rounded-2xl bg-blue-500 px-5 py-2.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-50 transition-all shadow-lg shadow-blue-500/20 active:scale-95"
                :disabled="extracting"
                @click="extractText"
              >
                <span class="flex items-center gap-1">✨ 解析</span>
              </button>
              <button
                v-if="contractText.trim() || uploadedFileName"
                class="rounded-2xl bg-white px-5 py-2.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-all border border-gray-200 shadow-sm active:scale-95"
                @click="clearAll"
              >
                清空
              </button>
            </div>
          </div>
          <div class="p-4 flex-1 flex flex-col gap-3">
            <textarea
              v-model="contractText"
              class="flex-1 min-h-[320px] resize-none rounded-2xl border border-gray-200/60 bg-gray-50/50 backdrop-blur-sm p-4 text-sm leading-6 outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:bg-white text-gray-900 placeholder-gray-400 transition-all"
              placeholder="粘贴合同全文，或上传 .txt/.md/.jpg/.png/.pdf"
            />
            <div class="text-xs text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
              <div>doc_id：<span class="font-mono">{{ docId || '未生成' }}</span></div>
              <div v-if="overallScore !== null">综合风险：<span class="font-mono">{{ overallScore }}</span></div>
            </div>
          </div>
        </section>

        <!-- Right: results + QA -->
        <section class="rounded-3xl border border-gray-200/60 bg-white/80 backdrop-blur-xl overflow-hidden flex flex-col h-[800px] shadow-lg shadow-gray-200/50">
          <div class="p-5 border-b border-gray-200/60 flex items-center justify-between bg-gray-50/50">
            <div class="flex items-center gap-2">
              <span class="text-lg">🔍</span>
              <div class="text-sm font-semibold text-gray-900">审查结果</div>
            </div>
            <div class="text-xs text-gray-500" v-if="clauses.length">共 {{ clauses.length }} 条</div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 p-4 flex-1 overflow-hidden">
            <div class="space-y-2 overflow-auto pr-1 h-full">
              <button
                v-for="c in clauses"
                :key="c.clause_id"
                class="w-full text-left rounded-2xl p-4 border border-gray-200/60 hover:border-blue-300 transition-all hover:shadow-lg active:scale-98"
                :class="selectedClauseId === c.clause_id ? 'bg-blue-50/80 backdrop-blur-sm border-blue-400 shadow-md' : 'bg-white/80 backdrop-blur-sm'"
                @click="selectedClauseId = c.clause_id"
              >
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-medium text-gray-900">{{ c.clause_type }}</span>
                  </div>
                  <span class="text-[11px] px-2.5 py-1 rounded-full font-semibold ring-1" :class="riskBadgeClass(c.risk_level)">
                    {{ c.risk_level.toUpperCase() }}
                  </span>
                </div>
                <div class="mt-2 text-xs text-gray-500 line-clamp-2">{{ c.risk_reason }}</div>
              </button>
            </div>

            <div class="rounded-2xl border border-gray-200/60 bg-white/80 backdrop-blur-sm p-4 overflow-auto">
              <div v-if="!selectedClause" class="flex flex-col items-center justify-center h-full text-center py-12">
                <span class="text-4xl mb-3">📊</span>
                <div class="text-sm text-gray-500">点击左侧条款查看详情</div>
              </div>
              <div v-else class="space-y-4">
                <div class="rounded-2xl bg-gray-50/80 p-4">
                  <div class="text-xs font-medium text-gray-600 mb-2 flex items-center gap-1">📝 条款原文</div>
                  <div class="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-900">{{ selectedClause.clause_text }}</div>
                </div>
                <div class="rounded-2xl bg-red-50/80 p-4">
                  <div class="text-xs font-medium text-red-700 mb-2 flex items-center gap-1">⚠️ 风险原因</div>
                  <div class="mt-1 text-sm leading-6 text-gray-900">{{ selectedClause.risk_reason }}</div>
                </div>
                <div class="rounded-2xl bg-gray-50/80 p-4">
                  <div class="text-xs font-medium text-gray-600 mb-2 flex items-center gap-1">⚖️ 法律依据</div>
                  <div class="mt-1 text-sm leading-6 text-gray-900">{{ selectedClause.legal_basis }}</div>
                </div>
                <div class="rounded-2xl bg-green-50/80 p-4">
                  <div class="text-xs font-medium text-green-700 mb-2 flex items-center gap-1">💡 修改建议</div>
                  <div class="mt-1 text-sm leading-6 text-gray-900">{{ selectedClause.suggestion }}</div>
                </div>
                <div class="rounded-2xl bg-amber-50/80 p-4">
                  <div class="text-xs font-medium text-amber-700 mb-2 flex items-center gap-1">💬 谈判话术</div>
                  <div class="mt-1 text-sm leading-6 text-gray-900">{{ selectedClause.negotiation_tip }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="border-t border-gray-200/60 p-4 space-y-3 bg-gray-50/50">
            <div class="text-sm font-semibold text-gray-900 flex items-center gap-2">💬 智能问答</div>
            <div class="flex gap-2">
              <input
                v-model="qaQuestion"
                class="flex-1 rounded-2xl border border-gray-200/60 bg-white/80 backdrop-blur-sm px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-gray-900 placeholder-gray-400 transition-all"
                placeholder="输入问题，或点击下方示例"
                @keyup.enter="qaQuestion.trim() && contractText.trim() && ask()"
              />
              <button
                class="rounded-2xl bg-blue-500 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50 transition-all shadow-lg shadow-blue-500/20 active:scale-95"
                :disabled="!qaQuestion.trim() || !contractText.trim()"
                @click="ask"
              >
                提问
              </button>
            </div>
            <div v-if="!qaAnswer" class="space-y-2">
              <div v-if="!contractText.trim()" class="rounded-2xl bg-gray-100/80 p-4 text-xs text-gray-500">
                请先上传或粘贴合同文本，即可开始提问。
              </div>
              <div class="flex flex-wrap gap-2">
                <span class="text-xs text-gray-500">试试问：</span>
                <button
                  v-for="q in sampleQuestions"
                  :key="q"
                  class="text-xs px-3 py-1.5 rounded-2xl bg-white/80 backdrop-blur-sm text-gray-700 hover:bg-gray-100 border border-gray-200/60 transition-all shadow-sm active:scale-95"
                  @click="qaQuestion = q"
                >
                  {{ q }}
                </button>
              </div>
            </div>
            <pre v-if="qaAnswer" class="max-h-48 overflow-auto rounded-2xl border border-gray-200/60 bg-white/80 backdrop-blur-sm p-4 text-xs leading-5 whitespace-pre-wrap text-gray-900 shadow-sm">{{ qaAnswer }}</pre>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

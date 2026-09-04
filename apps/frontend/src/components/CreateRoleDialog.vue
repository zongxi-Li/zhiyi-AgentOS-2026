<!-- 创建角色对话框 — 创建自定义 AI 角色的表单弹窗，含名称、描述和校验规则 -->
<template>
  <el-dialog
    v-model="visible"
    title="创建自定义角色"
    width="600px"
    @close="handleClose"
    class="role-dialog"
    :show-close="false"
    align-center
  >
    <template #header="{ close, titleId, titleClass }">
      <div class="dialog-header">
        <h4 :id="titleId" :class="titleClass">创建自定义角色</h4>
        <button class="close-btn" @click="close">
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </template>

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="role-form"
    >
      <el-form-item label="角色名称" prop="name">
        <el-input 
          v-model="form.name" 
          placeholder="给你的角色起个名字" 
          class="custom-input"
        />
      </el-form-item>

      <el-form-item label="角色描述" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="3"
          placeholder="简短描述这个角色的特点..."
          class="custom-input"
          resize="none"
        />
      </el-form-item>

      <el-form-item label="系统提示词 (Prompt)" prop="systemPrompt">
        <el-input
          v-model="form.systemPrompt"
          type="textarea"
          :rows="5"
          placeholder="设定角色的核心指令，例如：你是一个经验丰富的心理咨询师，你需要..."
          class="custom-input"
          resize="none"
        />
      </el-form-item>

      <div class="form-row">
        <el-form-item label="对话风格 (JSON)" class="half-width">
          <el-input
            v-model="form.dialogueStyleText"
            type="textarea"
            :rows="3"
            placeholder='{"tone": "warm", "style": "casual"}'
            class="custom-input"
            resize="none"
          />
        </el-form-item>

        <el-form-item label="性格特点 (JSON)" class="half-width">
          <el-input
            v-model="form.personalityText"
            type="textarea"
            :rows="3"
            placeholder='{"traits": ["patient", "professional"]}'
            class="custom-input"
            resize="none"
          />
        </el-form-item>
      </div>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose" class="cancel-btn">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="loading" class="submit-btn">
          创建角色
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { useRoleStore } from '@/stores/role'
import type { RoleCreateRequest } from '@/services/api/role'

interface Props {
  modelValue: boolean
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'created', role: any): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const roleStore = useRoleStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const form = reactive({
  name: '',
  description: '',
  systemPrompt: '',
  dialogueStyleText: '',
  personalityText: ''
})

const rules: FormRules = {
  name: [
    { required: true, message: '请输入角色名称', trigger: 'blur' }
  ],
  systemPrompt: [
    { required: true, message: '请输入系统提示词', trigger: 'blur' }
  ]
}

const handleClose = () => {
  formRef.value?.resetFields()
  visible.value = false
}

const handleSubmit = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const request: RoleCreateRequest = {
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          systemPrompt: form.systemPrompt.trim(),
          dialogueStyle: parseJson(form.dialogueStyleText, '对话风格'),
          personality: parseJson(form.personalityText, '性格特点')
        }

        const role = await roleStore.createRole(request)
        ElMessage.success('角色创建成功')
        emit('created', role)
        handleClose()
      } catch (error: any) {
        ElMessage.error(error.message || '创建角色失败')
      } finally {
        loading.value = false
      }
    }
  })
}

const parseJson = (text: string, fieldName: string = ''): any => {
  if (!text || !text.trim()) return undefined
  try {
    return JSON.parse(text)
  } catch (error) {
    if (text.trim()) {
      ElMessage.warning(`${fieldName || 'JSON'}格式错误，将忽略该配置`)
    }
    return undefined
  }
}

watch(() => props.modelValue, (val) => {
  if (val) {
    // 重置表单
    form.name = ''
    form.description = ''
    form.systemPrompt = ''
    form.dialogueStyleText = ''
    form.personalityText = ''
  }
})
</script>

<style scoped lang="scss">
// Dialog styles override (global override via class)
:deep(.role-dialog) {
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--bg-card) 92%, transparent);
  backdrop-filter: blur(24px);
  box-shadow: var(--shadow-lg);
  border: 1px solid color-mix(in srgb, var(--text-primary) 11%, var(--border-light));
  padding: 0;
  overflow: hidden;

  .el-dialog__header {
    margin: 0;
    padding: 0;
  }
  
  .el-dialog__body {
    padding: 20px 24px;
  }
  
  .el-dialog__footer {
    padding: 0;
  }
}

.dialog-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
  
  h4 {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
  }
  
  .close-btn {
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 8px;
    border-radius: 8px;
    color: var(--text-secondary);
    transition: all 0.2s;
    
    &:hover {
      background: var(--surface-hover);
      color: var(--text-primary);
    }
  }
}

.role-form {
  .custom-input {
    :deep(.el-input__wrapper),
    :deep(.el-textarea__inner) {
      background: var(--bg-input);
      box-shadow: 0 0 0 1px var(--border-light) inset;
      border-radius: 12px;
      padding: 10px 12px;
      transition: all 0.3s;
      
      &:hover {
        background: var(--surface-solid);
        box-shadow: 0 0 0 1px var(--border-hover) inset;
      }
      
      &.is-focus, &:focus {
        background: var(--surface-solid);
        box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 20%, transparent) inset;
      }
    }
  }
  
  .form-row {
    display: flex;
    gap: 20px;
    
    .half-width {
      flex: 1;
    }
  }
}

.dialog-footer {
  padding: 18px 24px;
  background: var(--surface-subtle);
  border-top: 1px solid var(--border-light);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  
  .cancel-btn {
    border-radius: 12px;
    padding: 10px 24px;
    border: 1px solid var(--border-light);
    background: var(--surface-subtle);
    
    &:hover {
      background: var(--bg-input);
      color: var(--text-primary);
    }
  }
  
  .submit-btn {
    border-radius: 12px;
    padding: 10px 24px;
    background: var(--primary-color);
    border: 1px solid var(--primary-color);
    font-weight: 600;
    
    &:hover {
      transform: translateY(-1px);
      box-shadow: var(--shadow-glow);
    }
  }
}
</style>

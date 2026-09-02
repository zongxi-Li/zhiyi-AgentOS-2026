<!-- 编辑角色对话框 — 编辑已有 AI 角色名称和描述的表单弹窗 -->
<template>
  <el-dialog
    v-model="visible"
    title="编辑角色"
    width="600px"
    @close="handleClose"
    class="role-dialog"
    :show-close="false"
    align-center
  >
    <template #header="{ close, titleId, titleClass }">
      <div class="dialog-header">
        <h4 :id="titleId" :class="titleClass">编辑角色</h4>
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
          保存修改
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { roleApi, type Role, type RoleCreateRequest } from '@/services/api/role'

interface Props {
  modelValue: boolean
  role?: Role | null
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'updated', role: Role): void
}

const props = withDefaults(defineProps<Props>(), {
  role: null
})

const emit = defineEmits<Emits>()

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
  if (!formRef.value || !props.role) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const request: RoleCreateRequest = {
          name: form.name,
          description: form.description,
          systemPrompt: form.systemPrompt,
          dialogueStyle: parseJson(form.dialogueStyleText),
          personality: parseJson(form.personalityText)
        }

        const role = await roleApi.updateRole(props.role.id, request)
        ElMessage.success('角色更新成功')
        emit('updated', role)
        handleClose()
      } catch (error: any) {
        ElMessage.error(error.message || '更新角色失败')
      } finally {
        loading.value = false
      }
    }
  })
}

const parseJson = (text: string): any => {
  if (!text || !text.trim()) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

const stringifyJson = (obj: any): string => {
  if (!obj) return ''
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return ''
  }
}

watch(() => props.modelValue, (val) => {
  if (val && props.role) {
    // 填充表单
    form.name = props.role.name || ''
    form.description = props.role.description || ''
    form.systemPrompt = props.role.systemPrompt || ''
    form.dialogueStyleText = stringifyJson(props.role.dialogueStyle)
    form.personalityText = stringifyJson(props.role.personality)
  } else {
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
// Same styles as CreateRoleDialog to maintain consistency
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

"use client"

import type { CSSProperties } from "react"
import {
  Alert,
  Button,
  Input,
  Layout,
  Select,
  Slider,
  Space,
  Typography,
} from "antd"
import { useEffect, useRef, useState } from "react"
import {
  CadDslResponse,
  ChatMessage,
  ParamMeta,
  formatAssistantContext,
  getCadDownload as downloadCadFile,
  getCadRequestErrorMessage,
  postCadChat,
} from "../lib/cad-api"
import CadViewer from "./components/cad-viewer"

type ParamState = Record<string, number>

const panelShell: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
  minWidth: 0,
  height: "100%",
  background: "#fff",
  border: "1px solid #f0f0f0",
  borderRadius: 8,
  overflow: "hidden",
}

const panelHeader: CSSProperties = {
  flexShrink: 0,
  padding: "10px 12px",
  borderBottom: "1px solid #f0f0f0",
  fontWeight: 600,
  fontSize: 14,
}

export default function Home() {
  const [scadTemplate, setScadTemplate] = useState("")
  const [renderedScad, setRenderedScad] = useState("")
  const [paramsMeta, setParamsMeta] = useState<ParamMeta[]>([])
  const [params, setParams] = useState<ParamState>({})
  const [isError, setIsError] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")
  const [cadID, setCadID] = useState<string>()
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const messagesScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = messagesScrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [chatMessages, sending])

  const applyCadResult = (cadObject: CadDslResponse) => {
    setScadTemplate(cadObject.scad)
    setRenderedScad(cadObject.scad)
    const initialParams = (cadObject.paramsMeta || []).reduce((acc: ParamState, p) => {
      acc[p.name] = p.value
      return acc
    }, {})
    setParamsMeta(cadObject.paramsMeta || [])
    setParams(initialParams)
    setCadID(cadObject.id)
  }

  const onSend = async () => {
    const text = input.trim()
    if (!text || sending) return
    const userTurn: ChatMessage = { role: "user", content: text }
    const historyForRequest = [...chatMessages, userTurn]
    setInput("")
    setChatMessages(historyForRequest)
    setSending(true)
    setIsError(false)
    setErrorMessage("")
    try {
      const cadObject = await postCadChat(historyForRequest)
      applyCadResult(cadObject)
      const replyText = cadObject.reply || "已更新模型。"
      const assistantTurn: ChatMessage = {
        role: "assistant",
        content: formatAssistantContext(replyText, cadObject.dsl),
      }
      setChatMessages([...historyForRequest, assistantTurn])
    } catch (error: unknown) {
      setIsError(true)
      setErrorMessage(getCadRequestErrorMessage(error))
    } finally {
      setSending(false)
    }
  }

  const onDownload = async (file_type: "stl" | "scad") => {
    if (cadID) {
      await downloadCadFile(cadID, file_type)
    }
  }

  const applyParams = (template: string, values: ParamState): string => {
    let out = template
    Object.entries(values).forEach(([name, value]) => {
      const fixed = Number(value.toFixed(4))
      const re = new RegExp(`(^|\\n)\\s*${name}\\s*=\\s*[-+]?\\d*\\.?\\d+\\s*;`, "m")
      out = out.replace(re, `$1${name} = ${fixed};`)
    })
    return out
  }

  const onChangeParam = (name: string, value: number) => {
    const next = { ...params, [name]: value }
    setParams(next)
    setRenderedScad(applyParams(scadTemplate, next))
  }

  const onUpdateModel = () => {
    if (!scadTemplate.trim()) return
    setRenderedScad(applyParams(scadTemplate, params))
  }

  return (
    <Layout style={{ height: "100dvh", maxHeight: "100dvh", overflow: "hidden", display: "flex", flexDirection: "column", background: "#f5f5f5" }}>
      <Layout.Header style={{ flexShrink: 0, background: "#fff", padding: "0 16px", lineHeight: "52px", height: 52, borderBottom: "1px solid #f0f0f0" }}>
        <Space wrap>
          <Typography.Text strong>CQAsk · 创模对话</Typography.Text>
          <Select placeholder="Download" style={{ width: 120 }} onChange={onDownload} options={[{ value: "scad", label: "SCAD" }, { value: "stl", label: "STL" }]} />
        </Space>
      </Layout.Header>

      {isError ? (
        <Alert
          style={{ flexShrink: 0, margin: "8px 16px 0" }}
          message="生成失败"
          description={errorMessage || "请重试或查看后端日志。"}
          type="error"
          showIcon
          closable
          onClose={() => setIsError(false)}
        />
      ) : null}

      <div className="cqask-main-row" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "row", gap: 12, padding: 12, overflow: "hidden" }}>
        <div className="cqask-chat-col" style={{ flex: "0 0 clamp(280px, 28vw, 400px)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={panelShell}>
            <div style={panelHeader}>创模 AI</div>
            <div ref={messagesScrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", padding: 10, background: "#fafafa" }}>
              {chatMessages.length === 0 ? (
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  在此输入自然语言描述零件；对话变长时仅本区域滚动，下方输入框始终可用。
                </Typography.Text>
              ) : (
                chatMessages.map((m, i) => {
                  const display = m.role === "assistant" && m.content.includes("\n[DSL_JSON]\n") ? m.content.split("\n[DSL_JSON]\n")[0] : m.content
                  return (
                    <div key={i} style={{ marginBottom: 10, textAlign: m.role === "user" ? "right" : "left" }}>
                      <Typography.Text style={{ display: "inline-block", maxWidth: "100%", padding: "8px 12px", borderRadius: 8, background: m.role === "user" ? "#1677ff" : "#fff", color: m.role === "user" ? "#fff" : "inherit", border: m.role === "user" ? "none" : "1px solid #e8e8e8", whiteSpace: "pre-wrap", textAlign: "left", fontSize: 13 }}>
                        {display}
                      </Typography.Text>
                    </div>
                  )
                })
              )}
            </div>
            <div style={{ flexShrink: 0, padding: 10, borderTop: "1px solid #f0f0f0", background: "#fff" }}>
              <Input.TextArea
                placeholder="请输入内容…"
                rows={3}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault()
                    onSend()
                  }
                }}
                disabled={sending}
                style={{ resize: "none" }}
              />
              <div style={{ marginTop: 8, textAlign: "right" }}>
                <Button type="primary" loading={sending} onClick={onSend}>
                  发送
                </Button>
              </div>
            </div>
          </div>
        </div>

        <div className="cqask-viewer-col" style={{ flex: "1 1 0", minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div style={{ ...panelShell, padding: 0 }}>
            <div style={{ ...panelHeader, borderRadius: "8px 8px 0 0" }}>三维预览</div>
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: 8 }}>
              <CadViewer scadScript={renderedScad} />
            </div>
          </div>
        </div>

        <div className="cqask-params-col" style={{ flex: "0 0 clamp(260px, 24vw, 360px)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={panelShell}>
            <div style={panelHeader}>特征参数修改</div>
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", padding: "8px 12px" }}>
              {paramsMeta.length === 0 ? (
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  生成模型后，可在此拖动滑条微调尺寸（本地实时生效）。
                </Typography.Text>
              ) : (
                <Space direction="vertical" style={{ width: "100%" }} size="middle">
                  {paramsMeta.map((p) => (
                    <div key={p.name}>
                      <Typography.Text style={{ fontSize: 13 }}>{p.label}</Typography.Text>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                        <Slider style={{ flex: 1 }} min={p.min} max={p.max} step={p.step} value={params[p.name] ?? p.value} onChange={(v) => onChangeParam(p.name, Number(v))} />
                        <Typography.Text type="secondary" style={{ width: 56, textAlign: "right", fontSize: 12 }}>
                          {Number(params[p.name] ?? p.value).toFixed(2)}
                        </Typography.Text>
                      </div>
                    </div>
                  ))}
                </Space>
              )}
            </div>
            <div style={{ flexShrink: 0, padding: 10, borderTop: "1px solid #f0f0f0", background: "#fff" }}>
              <Button type="primary" block onClick={onUpdateModel} disabled={!scadTemplate.trim()}>
                更新模型
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}

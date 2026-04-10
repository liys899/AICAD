"use client"


import { Alert, Layout, Select, Slider, Space, Typography } from 'antd'
import Search from 'antd/es/input/Search'
import { useState } from 'react'
import { CadDslResponse, ParamMeta, getCadDownload as downloadCadFile, getCadDsl as getCadObject } from './api/cad'
import CadViewer from './components/cad-viewer'
const { Content, } = Layout

type ParamState = Record<string, number>


export default function Home() {
  const [scadTemplate, setScadTemplate] = useState("")
  const [renderedScad, setRenderedScad] = useState("")
  const [paramsMeta, setParamsMeta] = useState<ParamMeta[]>([])
  const [params, setParams] = useState<ParamState>({})
  const [isError, setIsError] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")
  const [cadID, setCadID] = useState<string>()

  // const [UUID, setUUID] = useState<string>()

  const onSearch = async (value: string) => {
    try {
      setIsError(false)
      const cadObject: CadDslResponse = await getCadObject(value)
      setScadTemplate(cadObject.scad)
      setRenderedScad(cadObject.scad)
      const initialParams = (cadObject.paramsMeta || []).reduce((acc: ParamState, p) => {
        acc[p.name] = p.value
        return acc
      }, {})
      setParamsMeta(cadObject.paramsMeta || [])
      setParams(initialParams)
      setCadID(cadObject.id)
      setIsError(false)
      setErrorMessage("")
    } catch (error: any) {
      setIsError(true)
      setErrorMessage(error?.response?.data?.error?.message || "生成失败")
    }
  }

  const onDownload = async (file_type: "stl" | "scad") => {
    console.log(cadID, file_type)
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

  return (
    <Layout style={{ height: "100vh" }}>
      <Space wrap>
        <Select
          placeholder='Download'
          style={{ width: 120 }}
          onChange={onDownload}
          options={[
            { value: 'scad', label: 'SCAD' },
            { value: 'stl', label: 'STL' },
          ]}
        />
      </Space >

      <Layout>
        <Layout style={{ padding: '0 24px 24px' }}>
          <Content
            style={{
              margin: 0,
              minHeight: 280,
            }}
          >
            <Layout>
              <CadViewer scadScript={renderedScad} />

            </Layout>

          </Content>

          {
            isError ? (
              <Space direction="vertical" style={{ width: '100%' }}>

                <Alert
                  message="Error Generating"
                  description={errorMessage || "Please try again. Check backend logs for details."}
                  type="error"
                />
              </Space>
            ) : null
          }

          {paramsMeta.length > 0 ? (
            <Space direction="vertical" style={{ width: "100%", marginTop: 12 }}>
              <Typography.Text strong>参数调整（本地实时，不走 AI）</Typography.Text>
              {paramsMeta.map((p) => (
                <div key={p.name}>
                  <Typography.Text>{p.label}: {Number(params[p.name] ?? p.value).toFixed(2)}</Typography.Text>
                  <Slider
                    min={p.min}
                    max={p.max}
                    step={p.step}
                    value={params[p.name] ?? p.value}
                    onChange={(v) => onChangeParam(p.name, Number(v))}
                  />
                </div>
              ))}
            </Space>
          ) : null}


          <Search placeholder="input search text" size="large" onSearch={onSearch} />


        </Layout>



      </Layout>
    </Layout >
  )
}

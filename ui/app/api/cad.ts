import axios from "axios"
import { downloadAxiosResponse } from "../utils"

const BASE_URL = "http://127.0.0.1:5001"

export interface ParamMeta {
  name: string
  label: string
  min: number
  max: number
  step: number
  value: number
}

export interface CadDslResponse {
  id: string
  apiVersion: string
  pipeline: string
  dsl: Record<string, unknown>
  scad: string
  paramsMeta: ParamMeta[]
}

export function getCadDsl(query: string, uuid: string | null = null) {
  let config = {
    method: 'get',
    maxBodyLength: Infinity,
    "Content-Type": "application/json",
    url: `${BASE_URL}/cad`,
    headers: {},
    params: {
      query,
      uuid,
    },

  }

  return axios.request(config)
    .then(async (response) => {
      return response.data as CadDslResponse
    })
    .catch((error) => {
      throw error
    })
}


export function getCadDownload(id: string, file_type: "scad" | "stl") {
  let config = {
    method: 'get',
    maxBodyLength: Infinity,
    responseType: 'arraybuffer' as const,
    url: `${BASE_URL}/download`,
    headers: {
      "Content-Type": "application/json",
    },
    params: {
      id,
      file_type,
    },

  }

  return axios.request(config)
    .then(async (response) => {
      console.log(response)
      downloadAxiosResponse(`${id}.${file_type}`, response)
    })
    .catch((error) => {
      console.log(error)
    })
}



/// TTS 發音服務的 protocol 抽象
protocol Speaking: AnyObject {
    func speak(_ text: String)
}

/*
 * Reborn Office: thin, single-thread Emscripten bridge over upstream LibreOfficeKit.
 *
 * This intentionally does not use the Macro/chase custom WASM tile renderer.
 * It wraps the document that soffice/UNO already loaded and calls the standard
 * LibreOfficeKit document vtable (paintTile/input/UNO commands) directly.
 */

#if defined __EMSCRIPTEN__

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <emscripten.h>
#include <emscripten/bind.h>
#include <emscripten/val.h>

#include <LibreOfficeKit/LibreOfficeKitEnums.h>
#include <com/sun/star/lang/XComponent.hpp>
#include <com/sun/star/uno/Reference.hxx>
#include <comphelper/lok.hxx>
#include <lib/init.hxx>
#include <sfx2/viewsh.hxx>
#include <vcl/scheduler.hxx>

namespace
{
EM_JS(void, rowLokEmitCallback, (int type, const char* payload), {
    const text = payload ? UTF8ToString(payload) : '';
    if (typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope) {
        self.postMessage({
            rowOffice: true,
            kind: 'lok-callback',
            callbackType: type,
            payload: text
        });
    }
});

std::uint8_t unpremultiply(std::uint8_t channel, std::uint8_t alpha)
{
    if (alpha == 0)
        return 0;
    if (alpha == 255)
        return channel;
    const unsigned value = (static_cast<unsigned>(channel) * 255u + alpha / 2u) / alpha;
    return static_cast<std::uint8_t>(std::min(value, 255u));
}

class RowLokDocument final
{
public:
    RowLokDocument()
    {
        SfxViewShell* pViewShell = SfxViewShell::Current();
        if (!pViewShell)
            throw std::runtime_error("ROW_LOK_NO_CURRENT_VIEW");

        css::uno::Reference<css::lang::XComponent> xComponent(
            pViewShell->GetCurrentDocument(), css::uno::UNO_QUERY);
        if (!xComponent.is())
            throw std::runtime_error("ROW_LOK_NO_CURRENT_COMPONENT");

        const int nDocId = static_cast<int>(pViewShell->GetDocId().get());
        if (nDocId < 0)
            throw std::runtime_error("ROW_LOK_INVALID_DOCUMENT_ID");

        m_document = std::make_unique<desktop::LibLODocument_Impl>(xComponent, nDocId);
        m_document->pClass->registerCallback(m_document.get(), &RowLokDocument::callback, this);
    }

    ~RowLokDocument()
    {
        if (m_document && m_document->pClass)
            m_document->pClass->registerCallback(m_document.get(), nullptr, nullptr);
    }

    bool valid() const { return m_document && m_document->pClass; }

    void initializeForRendering(const std::string& args)
    {
        requireDocument();
        m_document->pClass->initializeForRendering(
            m_document.get(), args.empty() ? nullptr : args.c_str());
        Scheduler::ProcessEventsToIdle();
    }

    emscripten::val documentSize()
    {
        requireDocument();
        long width = 0;
        long height = 0;
        m_document->pClass->getDocumentSize(m_document.get(), &width, &height);
        emscripten::val result = emscripten::val::array();
        result.call<void>("push", width);
        result.call<void>("push", height);
        return result;
    }

    std::string pageRectangles()
    {
        requireDocument();
        char* raw = m_document->pClass->getPartPageRectangles(m_document.get());
        if (!raw)
            return {};
        std::string result(raw);
        std::free(raw);
        return result;
    }

    // ROW always exports straight (un-premultiplied) RGBA bytes to JavaScript,
    // independent of LibreOffice's native RGBA/BGRA tile mode.
    int tileMode()
    {
        requireDocument();
        return LOK_TILEMODE_RGBA;
    }

    emscripten::val paintTile(
        int canvasWidth,
        int canvasHeight,
        int tileXTwips,
        int tileYTwips,
        int tileWidthTwips,
        int tileHeightTwips)
    {
        requireDocument();
        if (canvasWidth <= 0 || canvasHeight <= 0)
            throw std::invalid_argument("ROW_LOK_BAD_CANVAS_SIZE");
        if (canvasWidth > 4096 || canvasHeight > 4096)
            throw std::invalid_argument("ROW_LOK_CANVAS_TOO_LARGE");

        const std::size_t pixels = static_cast<std::size_t>(canvasWidth)
                                 * static_cast<std::size_t>(canvasHeight);
        if (pixels > (64u * 1024u * 1024u) / 4u)
            throw std::invalid_argument("ROW_LOK_TILE_ALLOCATION_TOO_LARGE");

        m_tile.resize(pixels * 4u);
        const int nativeMode = m_document->pClass->getTileMode(m_document.get());
        m_document->pClass->paintTile(
            m_document.get(),
            m_tile.data(),
            canvasWidth,
            canvasHeight,
            tileXTwips,
            tileYTwips,
            tileWidthTwips,
            tileHeightTwips);

        if (nativeMode != LOK_TILEMODE_RGBA && nativeMode != LOK_TILEMODE_BGRA)
            throw std::runtime_error("ROW_LOK_UNKNOWN_NATIVE_TILE_MODE");

        for (std::size_t i = 0; i < m_tile.size(); i += 4)
        {
            const std::uint8_t alpha = m_tile[i + 3];
            const std::uint8_t native0 = m_tile[i + 0];
            const std::uint8_t native1 = m_tile[i + 1];
            const std::uint8_t native2 = m_tile[i + 2];
            const std::uint8_t red = nativeMode == LOK_TILEMODE_RGBA ? native0 : native2;
            const std::uint8_t green = native1;
            const std::uint8_t blue = nativeMode == LOK_TILEMODE_RGBA ? native2 : native0;
            m_tile[i + 0] = unpremultiply(red, alpha);
            m_tile[i + 1] = unpremultiply(green, alpha);
            m_tile[i + 2] = unpremultiply(blue, alpha);
        }

        return emscripten::val(
            emscripten::typed_memory_view(m_tile.size(), m_tile.data()));
    }

    void setClientZoom(int pixelWidth, int pixelHeight, int twipWidth, int twipHeight)
    {
        requireDocument();
        if (pixelWidth <= 0 || pixelHeight <= 0 || twipWidth <= 0 || twipHeight <= 0)
            throw std::invalid_argument("ROW_LOK_BAD_CLIENT_ZOOM");
        m_document->pClass->setClientZoom(
            m_document.get(), pixelWidth, pixelHeight, twipWidth, twipHeight);
        Scheduler::ProcessEventsToIdle();
    }

    int viewId()
    {
        requireDocument();
        return m_document->pClass->getView(m_document.get());
    }

    int createView()
    {
        requireDocument();
        const int result = m_document->pClass->createView(m_document.get());
        Scheduler::ProcessEventsToIdle();
        return result;
    }

    void setView(int viewId)
    {
        requireDocument();
        m_document->pClass->setView(m_document.get(), viewId);
        Scheduler::ProcessEventsToIdle();
    }

    void postKeyEvent(int type, int charCode, int keyCode)
    {
        requireDocument();
        m_document->pClass->postKeyEvent(m_document.get(), type, charCode, keyCode);
        Scheduler::ProcessEventsToIdle();
    }

    void postTextInput(const std::string& text)
    {
        requireDocument();
        m_document->pClass->postWindowExtTextInputEvent(
            m_document.get(), 0, LOK_EXT_TEXTINPUT, text.c_str());
        m_document->pClass->postWindowExtTextInputEvent(
            m_document.get(), 0, LOK_EXT_TEXTINPUT_END, text.c_str());
        Scheduler::ProcessEventsToIdle();
    }

    void removeTextContext(int before, int after)
    {
        requireDocument();
        m_document->pClass->removeTextContext(m_document.get(), 0, before, after);
        Scheduler::ProcessEventsToIdle();
    }

    void postMouseEvent(int type, int xTwips, int yTwips, int count, int buttons, int modifiers)
    {
        requireDocument();
        m_document->pClass->postMouseEvent(
            m_document.get(), type, xTwips, yTwips, count, buttons, modifiers);
        Scheduler::ProcessEventsToIdle();
    }

    void postUnoCommand(const std::string& command, const std::string& args, bool notifyWhenFinished)
    {
        requireDocument();
        m_document->pClass->postUnoCommand(
            m_document.get(),
            command.c_str(),
            args.empty() ? nullptr : args.c_str(),
            notifyWhenFinished);
        Scheduler::ProcessEventsToIdle();
    }

    void setTextSelection(int type, int xTwips, int yTwips)
    {
        requireDocument();
        m_document->pClass->setTextSelection(m_document.get(), type, xTwips, yTwips);
        Scheduler::ProcessEventsToIdle();
    }

    void setClientVisibleArea(int xTwips, int yTwips, int widthTwips, int heightTwips)
    {
        requireDocument();
        m_document->pClass->setClientVisibleArea(
            m_document.get(), xTwips, yTwips, widthTwips, heightTwips);
    }

    std::string textSelection()
    {
        requireDocument();
        char* usedMime = nullptr;
        char* text = m_document->pClass->getTextSelection(
            m_document.get(), "text/plain;charset=utf-8", &usedMime);
        std::string result = text ? text : "";
        std::free(text);
        std::free(usedMime);
        return result;
    }

private:
    static void callback(int type, const char* payload, void*)
    {
        rowLokEmitCallback(type, payload);
    }

    void requireDocument() const
    {
        if (!valid())
            throw std::runtime_error("ROW_LOK_DOCUMENT_NOT_READY");
    }

    std::unique_ptr<desktop::LibLODocument_Impl> m_document;
    std::vector<std::uint8_t> m_tile;
};

void rowLokSetActive(bool active)
{
    comphelper::LibreOfficeKit::setActive(active);
}

void rowLokProcessEventsToIdle()
{
    Scheduler::ProcessEventsToIdle();
}
}

EMSCRIPTEN_BINDINGS(row_lok_bridge)
{
    emscripten::function("rowLokSetActive", &rowLokSetActive);
    emscripten::function("rowLokProcessEventsToIdle", &rowLokProcessEventsToIdle);

    emscripten::class_<RowLokDocument>("RowLokDocument")
        .constructor<>()
        .function("valid", &RowLokDocument::valid)
        .function("initializeForRendering", &RowLokDocument::initializeForRendering)
        .function("documentSize", &RowLokDocument::documentSize)
        .function("pageRectangles", &RowLokDocument::pageRectangles)
        .function("tileMode", &RowLokDocument::tileMode)
        .function("paintTile", &RowLokDocument::paintTile)
        .function("setClientZoom", &RowLokDocument::setClientZoom)
        .function("viewId", &RowLokDocument::viewId)
        .function("createView", &RowLokDocument::createView)
        .function("setView", &RowLokDocument::setView)
        .function("postKeyEvent", &RowLokDocument::postKeyEvent)
        .function("postTextInput", &RowLokDocument::postTextInput)
        .function("removeTextContext", &RowLokDocument::removeTextContext)
        .function("postMouseEvent", &RowLokDocument::postMouseEvent)
        .function("postUnoCommand", &RowLokDocument::postUnoCommand)
        .function("setTextSelection", &RowLokDocument::setTextSelection)
        .function("setClientVisibleArea", &RowLokDocument::setClientVisibleArea)
        .function("textSelection", &RowLokDocument::textSelection);
}

#endif

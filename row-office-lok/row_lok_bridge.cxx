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

#include <emscripten/bind.h>
#include <emscripten/val.h>

#include <com/sun/star/lang/XComponent.hpp>
#include <com/sun/star/uno/Reference.hxx>
#include <com/sun/star/uno/UNO_QUERY.hxx>
#include <comphelper/lok.hxx>
#include <desktop/inc/lib/init.hxx>
#include <sfx2/viewsh.hxx>

namespace
{
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
    }

    bool valid() const { return m_document && m_document->pClass; }

    void initializeForRendering(const std::string& args)
    {
        requireDocument();
        m_document->pClass->initializeForRendering(
            m_document.get(), args.empty() ? nullptr : args.c_str());
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

    int tileMode()
    {
        requireDocument();
        return m_document->pClass->getTileMode(m_document.get());
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
        m_document->pClass->paintTile(
            m_document.get(),
            m_tile.data(),
            canvasWidth,
            canvasHeight,
            tileXTwips,
            tileYTwips,
            tileWidthTwips,
            tileHeightTwips);

        return emscripten::val(
            emscripten::typed_memory_view(m_tile.size(), m_tile.data()));
    }

    int viewId()
    {
        requireDocument();
        return m_document->pClass->getView(m_document.get());
    }

    int createView()
    {
        requireDocument();
        return m_document->pClass->createView(m_document.get());
    }

    void setView(int viewId)
    {
        requireDocument();
        m_document->pClass->setView(m_document.get(), viewId);
    }

    void postKeyEvent(int type, int charCode, int keyCode)
    {
        requireDocument();
        m_document->pClass->postKeyEvent(m_document.get(), type, charCode, keyCode);
    }

    void postMouseEvent(int type, int xTwips, int yTwips, int count, int buttons, int modifiers)
    {
        requireDocument();
        m_document->pClass->postMouseEvent(
            m_document.get(), type, xTwips, yTwips, count, buttons, modifiers);
    }

    void postUnoCommand(const std::string& command, const std::string& args, bool notifyWhenFinished)
    {
        requireDocument();
        m_document->pClass->postUnoCommand(
            m_document.get(),
            command.c_str(),
            args.empty() ? nullptr : args.c_str(),
            notifyWhenFinished);
    }

    void setTextSelection(int type, int xTwips, int yTwips)
    {
        requireDocument();
        m_document->pClass->setTextSelection(m_document.get(), type, xTwips, yTwips);
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
}

EMSCRIPTEN_BINDINGS(row_lok_bridge)
{
    emscripten::function("rowLokSetActive", &rowLokSetActive);

    emscripten::class_<RowLokDocument>("RowLokDocument")
        .constructor<>()
        .function("valid", &RowLokDocument::valid)
        .function("initializeForRendering", &RowLokDocument::initializeForRendering)
        .function("documentSize", &RowLokDocument::documentSize)
        .function("pageRectangles", &RowLokDocument::pageRectangles)
        .function("tileMode", &RowLokDocument::tileMode)
        .function("paintTile", &RowLokDocument::paintTile)
        .function("viewId", &RowLokDocument::viewId)
        .function("createView", &RowLokDocument::createView)
        .function("setView", &RowLokDocument::setView)
        .function("postKeyEvent", &RowLokDocument::postKeyEvent)
        .function("postMouseEvent", &RowLokDocument::postMouseEvent)
        .function("postUnoCommand", &RowLokDocument::postUnoCommand)
        .function("setTextSelection", &RowLokDocument::setTextSelection)
        .function("setClientVisibleArea", &RowLokDocument::setClientVisibleArea)
        .function("textSelection", &RowLokDocument::textSelection);
}

#endif

from rest_framework import serializers

from documents.models import DocumentStatus, ExtractedData, InvoiceDocument, LineItem
from documents.services.duplicate_detection import detect_duplicate_on_upload


class LineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = ("id", "description", "quantity", "unit_price", "line_total", "ordering")


class ExtractedDataSerializer(serializers.ModelSerializer):
    line_items = LineItemSerializer(many=True, read_only=True)

    class Meta:
        model = ExtractedData
        fields = (
            "vendor_name",
            "date_issued",
            "invoice_number",
            "document_type",
            "subtotal",
            "tax_amount",
            "total_amount",
            "category",
            "line_items",
        )


class InvoiceDocumentSerializer(serializers.ModelSerializer):
    extracted = ExtractedDataSerializer(read_only=True)

    class Meta:
        model = InvoiceDocument
        fields = (
            "id",
            "original_filename",
            "upload_date",
            "status",
            "confidence_score",
            "extraction_error",
            "extracted",
        )
        read_only_fields = ("id", "upload_date", "status", "confidence_score", "extraction_error", "extracted")


class InvoiceDocumentCreateSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)

    class Meta:
        model = InvoiceDocument
        fields = ("file",)

    def create(self, validated_data):
        upload = validated_data["file"]
        user = self.context["request"].user
        raw_bytes = upload.read()
        upload.seek(0)
        doc = InvoiceDocument(
            uploaded_by=user,
            original_filename=getattr(upload, "name", "") or "",
        )
        doc.set_file_hash(raw_bytes)
        doc.file.save(upload.name, upload, save=True)
        detect_duplicate_on_upload(doc)
        doc.save(
            update_fields=[
                "file_sha256",
                "duplicate_group",
                "is_duplicate",
                "duplicate_confidence",
                "canonical_document",
                "duplicate_reason",
            ]
        )
        return doc
